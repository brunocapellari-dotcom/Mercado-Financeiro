from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from threading import RLock
from typing import Protocol

from mercado_financeiro.risk import (
    DeterministicRiskEngine,
    KillSwitch,
    OrderIntent,
    RiskContext,
)


@dataclass(frozen=True)
class BrokerOrderAck:
    broker_order_id: str
    status: str


class BrokerSubmissionOutcomeUnknown(RuntimeError):
    """Raised when the request may have reached the venue but no final state is known."""


class BrokerAdapter(Protocol):
    """Execution-only broker boundary.

    Implementations own broker authentication. Credentials must never be
    exposed through this protocol or passed into LLM/research code. An adapter
    must raise ``BrokerSubmissionOutcomeUnknown`` whenever a state-changing
    request may have reached the broker but its final outcome is unknown.
    """

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        ...


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool | None
    status: str
    client_order_id: str
    broker_order_id: str | None
    risk_reasons: tuple[str, ...]
    duplicate: bool = False
    requires_reconciliation: bool = False


class IdempotencyConflict(RuntimeError):
    pass


class IdempotencyStore(Protocol):
    """Atomic idempotency boundary used by the execution engine.

    Live implementations must persist the key/fingerprint/result durably and
    enforce uniqueness across every execution replica.
    """

    live_safe: bool

    def get(self, key: str) -> tuple[str, ExecutionResult] | None:
        ...

    def put_if_absent(self, key: str, fingerprint: str, result: ExecutionResult) -> bool:
        ...


class InMemoryIdempotencyStore:
    """Reference idempotency store for tests/paper.

    Production live must replace this with a durable atomic store/transaction
    and retain the deterministic client_order_id at the broker boundary.
    """

    live_safe = False

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, ExecutionResult]] = {}
        self._lock = RLock()

    def get(self, key: str) -> tuple[str, ExecutionResult] | None:
        with self._lock:
            return self._records.get(key)

    def put_if_absent(self, key: str, fingerprint: str, result: ExecutionResult) -> bool:
        with self._lock:
            if key in self._records:
                return False
            self._records[key] = (fingerprint, result)
            return True


class DeterministicExecutionEngine:
    """Execution path that cannot bypass deterministic pre-trade risk.

    Unknown transport outcomes are never blindly retried. The idempotency key is
    sealed as ``submission_ambiguous`` and must be resolved by broker query or
    reconciliation before the system can make a new state-changing decision.
    When an independent kill switch is configured, its state is read inside the
    execution boundary so strategy/model code cannot suppress it.
    """

    def __init__(
        self,
        *,
        risk_engine: DeterministicRiskEngine,
        broker: BrokerAdapter,
        idempotency_store: IdempotencyStore | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self._risk_engine = risk_engine
        self._broker = broker
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._kill_switch = kill_switch
        self._execution_lock = RLock()

    @property
    def idempotency_store_live_safe(self) -> bool:
        return bool(getattr(self._idempotency, "live_safe", False))

    @property
    def kill_switch_live_safe(self) -> bool:
        return bool(self._kill_switch is not None and getattr(self._kill_switch, "live_safe", False))

    def execute(self, order: OrderIntent, context: RiskContext) -> ExecutionResult:
        # Reference runtime serializes check -> risk -> submit -> persist so two
        # local threads cannot duplicate an order. Production must additionally
        # use a durable atomic store and broker-side client_order_id deduplication
        # to cover process/node failures.
        with self._execution_lock:
            fingerprint = self._fingerprint(order)
            existing = self._idempotency.get(order.idempotency_key)
            if existing is not None:
                existing_fingerprint, existing_result = existing
                if existing_fingerprint != fingerprint:
                    raise IdempotencyConflict("idempotency key reused with different order payload")
                return ExecutionResult(
                    accepted=existing_result.accepted,
                    status=existing_result.status,
                    client_order_id=existing_result.client_order_id,
                    broker_order_id=existing_result.broker_order_id,
                    risk_reasons=existing_result.risk_reasons,
                    duplicate=True,
                    requires_reconciliation=existing_result.requires_reconciliation,
                )

            client_order_id = self._client_order_id(order)
            if self._kill_switch is not None:
                try:
                    switch_state = self._kill_switch.status()
                except Exception:
                    result = ExecutionResult(
                        accepted=False,
                        status="risk_rejected",
                        client_order_id=client_order_id,
                        broker_order_id=None,
                        risk_reasons=("kill_switch_status_unavailable",),
                    )
                    if not self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result):
                        raise IdempotencyConflict("idempotency store changed during kill-switch rejection")
                    return result
                context = replace(
                    context,
                    kill_switch_engaged=context.kill_switch_engaged or switch_state.engaged,
                )

            decision = self._risk_engine.evaluate(order, context)
            if not decision.approved:
                result = ExecutionResult(
                    accepted=False,
                    status="risk_rejected",
                    client_order_id=client_order_id,
                    broker_order_id=None,
                    risk_reasons=decision.reasons,
                )
                if not self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result):
                    raise IdempotencyConflict("idempotency store changed during rejection")
                return result

            try:
                ack = self._broker.submit_order(order, client_order_id=client_order_id)
            except (BrokerSubmissionOutcomeUnknown, TimeoutError, ConnectionError, OSError):
                result = ExecutionResult(
                    accepted=None,
                    status="submission_ambiguous",
                    client_order_id=client_order_id,
                    broker_order_id=None,
                    risk_reasons=(),
                    requires_reconciliation=True,
                )
                if not self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result):
                    raise IdempotencyConflict("idempotency store changed after ambiguous submission")
                return result

            result = ExecutionResult(
                accepted=True,
                status=ack.status,
                client_order_id=client_order_id,
                broker_order_id=ack.broker_order_id,
                risk_reasons=(),
            )
            if not self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result):
                raise IdempotencyConflict("idempotency store changed during execution")
            return result

    @staticmethod
    def _client_order_id(order: OrderIntent) -> str:
        digest = sha256(order.idempotency_key.encode("utf-8")).hexdigest()[:24]
        return f"mf-{digest}"

    @staticmethod
    def _fingerprint(order: OrderIntent) -> str:
        canonical = "|".join(
            (
                order.instrument,
                order.side,
                str(order.quantity),
                str(order.price),
                order.signal_id,
                order.created_at.isoformat(),
            )
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

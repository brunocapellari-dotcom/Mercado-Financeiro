from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskContext


@dataclass(frozen=True)
class BrokerOrderAck:
    broker_order_id: str
    status: str


class BrokerAdapter(Protocol):
    """Execution-only broker boundary.

    Implementations own broker authentication. Credentials must never be
    exposed through this protocol or passed into LLM/research code.
    """

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        ...


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    status: str
    client_order_id: str
    broker_order_id: str | None
    risk_reasons: tuple[str, ...]
    duplicate: bool = False


class IdempotencyConflict(RuntimeError):
    pass


class InMemoryIdempotencyStore:
    """Reference idempotency store for tests/paper.

    Production live must replace this with a durable atomic store/transaction.
    """

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, ExecutionResult]] = {}

    def get(self, key: str) -> tuple[str, ExecutionResult] | None:
        return self._records.get(key)

    def put_if_absent(self, key: str, fingerprint: str, result: ExecutionResult) -> bool:
        if key in self._records:
            return False
        self._records[key] = (fingerprint, result)
        return True


class DeterministicExecutionEngine:
    """Execution path that cannot bypass deterministic pre-trade risk."""

    def __init__(
        self,
        *,
        risk_engine: DeterministicRiskEngine,
        broker: BrokerAdapter,
        idempotency_store: InMemoryIdempotencyStore | None = None,
    ) -> None:
        self._risk_engine = risk_engine
        self._broker = broker
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()

    def execute(self, order: OrderIntent, context: RiskContext) -> ExecutionResult:
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
            )

        decision = self._risk_engine.evaluate(order, context)
        client_order_id = self._client_order_id(order)
        if not decision.approved:
            result = ExecutionResult(
                accepted=False,
                status="risk_rejected",
                client_order_id=client_order_id,
                broker_order_id=None,
                risk_reasons=decision.reasons,
            )
            self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result)
            return result

        ack = self._broker.submit_order(order, client_order_id=client_order_id)
        result = ExecutionResult(
            accepted=True,
            status=ack.status,
            client_order_id=client_order_id,
            broker_order_id=ack.broker_order_id,
            risk_reasons=(),
        )
        if not self._idempotency.put_if_absent(order.idempotency_key, fingerprint, result):
            # A production durable store must make check+submit+persist atomic or
            # broker-side client_order_id idempotency must guarantee no duplicate.
            raise IdempotencyConflict("concurrent idempotency race detected")
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

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Mapping

from mercado_financeiro.accounting import PortfolioAccountingLedger
from mercado_financeiro.execution.brokerage import (
    DeterministicBrokerageModel,
    MarketExecutionState,
    SimulatedFill,
)
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskContext
from mercado_financeiro.runtime import RuntimeMode


@dataclass(frozen=True)
class PaperOrderRecord:
    order_id: str
    signal_id: str
    instrument: str
    side: str
    quantity: Decimal
    requested_price: Decimal
    status: str
    created_at: datetime
    risk_reasons: tuple[str, ...] = ()
    fill_price: Decimal | None = None
    fee: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    realized_pnl_delta: Decimal = Decimal("0")
    duplicate: bool = False


@dataclass(frozen=True)
class PaperShadowSnapshot:
    mode: RuntimeMode
    orders: int
    fills: int
    rejected: int
    duplicates: int
    turnover: Decimal
    fees: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    equity: Decimal | None
    gross_exposure: Decimal | None
    positions: Mapping[str, Decimal]
    records: tuple[PaperOrderRecord, ...]


class PaperShadowSession:
    """Deterministic paper/shadow execution loop.

    The session never has a live broker boundary. Every order is evaluated by the
    independent deterministic Risk Manager before the configured brokerage model
    may simulate a fill. Fills are applied exactly once to the Decimal accounting
    ledger and retain signal-level cost/P&L attribution.
    """

    def __init__(
        self,
        *,
        mode: RuntimeMode,
        risk_engine: DeterministicRiskEngine,
        brokerage: DeterministicBrokerageModel,
        initial_cash: Decimal,
    ) -> None:
        if mode not in {RuntimeMode.PAPER, RuntimeMode.SHADOW}:
            raise ValueError("PaperShadowSession accepts only PAPER or SHADOW mode")
        self._mode = mode
        self._risk = risk_engine
        self._brokerage = brokerage
        self._ledger = PortfolioAccountingLedger(initial_cash=initial_cash)
        self._records: list[PaperOrderRecord] = []
        self._idempotency: dict[str, tuple[str, PaperOrderRecord]] = {}

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def process_order(
        self,
        order: OrderIntent,
        *,
        risk_context: RiskContext,
        market: MarketExecutionState,
    ) -> PaperOrderRecord:
        fingerprint = self._fingerprint(order)
        existing = self._idempotency.get(order.idempotency_key)
        if existing is not None:
            previous_fingerprint, previous = existing
            if previous_fingerprint != fingerprint:
                raise ValueError("idempotency key reused with different paper order payload")
            duplicate = replace(previous, duplicate=True)
            self._records.append(duplicate)
            return duplicate

        current = self._ledger.snapshot().positions.get(order.instrument)
        actual_position = current.quantity if current is not None else Decimal("0")
        context = replace(risk_context, current_position=actual_position)
        decision = self._risk.evaluate(order, context)
        if not decision.approved:
            record = PaperOrderRecord(
                order_id=order.idempotency_key,
                signal_id=order.signal_id,
                instrument=order.instrument,
                side=order.side,
                quantity=order.quantity,
                requested_price=order.price,
                status="risk_rejected",
                created_at=order.created_at,
                risk_reasons=decision.reasons,
            )
            return self._remember(order.idempotency_key, fingerprint, record)

        fill = self._brokerage.simulate_market_order(
            order,
            market,
            cash_available=self._ledger.snapshot().cash,
        )
        if not fill.filled:
            record = PaperOrderRecord(
                order_id=order.idempotency_key,
                signal_id=order.signal_id,
                instrument=order.instrument,
                side=order.side,
                quantity=order.quantity,
                requested_price=order.price,
                status=f"fill_rejected:{fill.reason}",
                created_at=order.created_at,
            )
            return self._remember(order.idempotency_key, fingerprint, record)

        record = self._apply_fill(order, fill)
        return self._remember(order.idempotency_key, fingerprint, record)

    def snapshot(
        self,
        *,
        marks: Mapping[str, Decimal] | None = None,
    ) -> PaperShadowSnapshot:
        ledger = self._ledger.snapshot()
        mtm = self._ledger.mark_to_market(marks) if marks is not None else None
        canonical_records = [row for row in self._records if not row.duplicate]
        return PaperShadowSnapshot(
            mode=self._mode,
            orders=len(canonical_records),
            fills=sum(1 for row in canonical_records if row.status == "filled"),
            rejected=sum(1 for row in canonical_records if row.status != "filled"),
            duplicates=sum(1 for row in self._records if row.duplicate),
            turnover=sum(
                (
                    row.quantity * row.fill_price
                    for row in canonical_records
                    if row.status == "filled" and row.fill_price is not None
                ),
                Decimal("0"),
            ),
            fees=ledger.cumulative_fees,
            realized_pnl=ledger.realized_pnl,
            unrealized_pnl=mtm.unrealized_pnl if mtm is not None else None,
            equity=mtm.equity if mtm is not None else None,
            gross_exposure=mtm.gross_exposure if mtm is not None else None,
            positions={key: value.quantity for key, value in ledger.positions.items()},
            records=tuple(self._records),
        )

    def _apply_fill(self, order: OrderIntent, fill: SimulatedFill) -> PaperOrderRecord:
        assert fill.fill_price is not None
        before = self._ledger.snapshot().realized_pnl
        signed_quantity = order.quantity if order.side == "buy" else -order.quantity
        fill_id = "paper-" + sha256(
            f"{order.idempotency_key}|{fill.fill_price}|{fill.quantity}".encode("utf-8")
        ).hexdigest()[:24]
        self._ledger.apply_fill(
            fill_id=fill_id,
            instrument=order.instrument,
            signed_quantity=signed_quantity,
            price=fill.fill_price,
            fee=fill.fee,
        )
        realized_delta = self._ledger.snapshot().realized_pnl - before
        return PaperOrderRecord(
            order_id=order.idempotency_key,
            signal_id=order.signal_id,
            instrument=order.instrument,
            side=order.side,
            quantity=fill.quantity,
            requested_price=order.price,
            status="filled",
            created_at=order.created_at,
            fill_price=fill.fill_price,
            fee=fill.fee,
            slippage_bps=fill.slippage_bps,
            realized_pnl_delta=realized_delta,
        )

    def _remember(
        self,
        key: str,
        fingerprint: str,
        record: PaperOrderRecord,
    ) -> PaperOrderRecord:
        self._idempotency[key] = (fingerprint, record)
        self._records.append(record)
        return record

    @staticmethod
    def _fingerprint(order: OrderIntent) -> str:
        material = "|".join(
            (
                order.instrument,
                order.side,
                str(order.quantity),
                str(order.price),
                order.signal_id,
                order.created_at.isoformat(),
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()

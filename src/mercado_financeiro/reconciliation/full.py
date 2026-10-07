from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from .engine import DeterministicReconciler, ReconciliationMismatch


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    instrument: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.fill_id.strip() or not self.instrument.strip():
            raise ValueError("fill_id and instrument are required")
        if self.quantity == 0 or self.price <= 0 or self.fee < 0:
            raise ValueError("invalid fill economics")


@dataclass(frozen=True)
class ExecutionLedgerSnapshot:
    positions: Mapping[str, Decimal]
    cash: Decimal
    cumulative_fees: Decimal
    realized_pnl: Decimal
    open_orders: Mapping[str, str]
    fills: Mapping[str, FillRecord]

    def __post_init__(self) -> None:
        if self.cumulative_fees < 0:
            raise ValueError("cumulative_fees cannot be negative")


@dataclass(frozen=True)
class FullReconciliationResult:
    approved: bool
    position_mismatches: tuple[ReconciliationMismatch, ...]
    cash_mismatch: ReconciliationMismatch | None
    fee_mismatch: ReconciliationMismatch | None
    realized_pnl_mismatch: ReconciliationMismatch | None
    order_mismatches: tuple[str, ...]
    fill_mismatches: tuple[str, ...]


class DeterministicFullReconciler:
    """Reconcile the complete execution ledger, not only positions/cash."""

    def __init__(
        self,
        *,
        position_tolerance: Decimal = Decimal("0"),
        cash_tolerance: Decimal = Decimal("0.01"),
        fee_tolerance: Decimal = Decimal("0.01"),
        pnl_tolerance: Decimal = Decimal("0.01"),
        fill_price_tolerance: Decimal = Decimal("0.0001"),
        fill_quantity_tolerance: Decimal = Decimal("0"),
    ) -> None:
        for name, value in (
            ("position_tolerance", position_tolerance),
            ("cash_tolerance", cash_tolerance),
            ("fee_tolerance", fee_tolerance),
            ("pnl_tolerance", pnl_tolerance),
            ("fill_price_tolerance", fill_price_tolerance),
            ("fill_quantity_tolerance", fill_quantity_tolerance),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        self._base = DeterministicReconciler(
            position_tolerance=position_tolerance,
            cash_tolerance=cash_tolerance,
        )
        self._fee_tolerance = fee_tolerance
        self._pnl_tolerance = pnl_tolerance
        self._fill_price_tolerance = fill_price_tolerance
        self._fill_quantity_tolerance = fill_quantity_tolerance

    def reconcile(
        self,
        *,
        internal: ExecutionLedgerSnapshot,
        broker: ExecutionLedgerSnapshot,
    ) -> FullReconciliationResult:
        base = self._base.reconcile(
            internal_positions=internal.positions,
            broker_positions=broker.positions,
            internal_cash=internal.cash,
            broker_cash=broker.cash,
        )
        fee_mismatch = self._decimal_mismatch(
            "cumulative_fees",
            internal.cumulative_fees,
            broker.cumulative_fees,
            self._fee_tolerance,
        )
        pnl_mismatch = self._decimal_mismatch(
            "realized_pnl",
            internal.realized_pnl,
            broker.realized_pnl,
            self._pnl_tolerance,
        )

        order_mismatches: list[str] = []
        for order_id in sorted(set(internal.open_orders) | set(broker.open_orders)):
            order_left = internal.open_orders.get(order_id)
            order_right = broker.open_orders.get(order_id)
            if order_left != order_right:
                order_mismatches.append(
                    f"{order_id}:{order_left!r}!={order_right!r}"
                )

        fill_mismatches: list[str] = []
        for fill_id in sorted(set(internal.fills) | set(broker.fills)):
            fill_left = internal.fills.get(fill_id)
            fill_right = broker.fills.get(fill_id)
            if fill_left is None or fill_right is None:
                missing_side = "internal" if fill_left is None else "broker"
                fill_mismatches.append(f"{fill_id}:missing_on_{missing_side}")
                continue
            if fill_left.instrument != fill_right.instrument:
                fill_mismatches.append(f"{fill_id}:instrument")
                continue
            if abs(fill_left.quantity - fill_right.quantity) > self._fill_quantity_tolerance:
                fill_mismatches.append(f"{fill_id}:quantity")
            if abs(fill_left.price - fill_right.price) > self._fill_price_tolerance:
                fill_mismatches.append(f"{fill_id}:price")
            if abs(fill_left.fee - fill_right.fee) > self._fee_tolerance:
                fill_mismatches.append(f"{fill_id}:fee")

        approved = (
            base.approved
            and fee_mismatch is None
            and pnl_mismatch is None
            and not order_mismatches
            and not fill_mismatches
        )
        return FullReconciliationResult(
            approved=approved,
            position_mismatches=base.position_mismatches,
            cash_mismatch=base.cash_mismatch,
            fee_mismatch=fee_mismatch,
            realized_pnl_mismatch=pnl_mismatch,
            order_mismatches=tuple(order_mismatches),
            fill_mismatches=tuple(fill_mismatches),
        )

    @staticmethod
    def _decimal_mismatch(
        key: str,
        internal: Decimal,
        broker: Decimal,
        tolerance: Decimal,
    ) -> ReconciliationMismatch | None:
        difference = broker - internal
        if abs(difference) <= tolerance:
            return None
        return ReconciliationMismatch(
            key=key,
            internal_value=internal,
            broker_value=broker,
            difference=difference,
        )

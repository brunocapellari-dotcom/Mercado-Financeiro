from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


class DuplicateFillError(RuntimeError):
    pass


@dataclass(frozen=True)
class PositionAccounting:
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.average_price < 0:
            raise ValueError("average_price cannot be negative")
        if self.quantity == 0 and self.average_price != 0:
            raise ValueError("flat position must have zero average_price")
        if self.quantity != 0 and self.average_price <= 0:
            raise ValueError("open position requires positive average_price")


@dataclass(frozen=True)
class PortfolioAccountingSnapshot:
    cash: Decimal
    cumulative_fees: Decimal
    realized_pnl: Decimal
    positions: Mapping[str, PositionAccounting]
    applied_fill_ids: tuple[str, ...]


@dataclass(frozen=True)
class MarkToMarketSnapshot:
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    gross_exposure: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    cumulative_fees: Decimal


class PortfolioAccountingLedger:
    """Deterministic single-currency accounting ledger for the initial B3 runtime.

    Quantities are signed: buys are positive and sells are negative. Fees are
    tracked separately from gross realized P&L so reconciliation can compare both
    independently. The ledger is intentionally broker-agnostic and uses Decimal
    throughout its accounting boundary.
    """

    def __init__(self, *, initial_cash: Decimal = Decimal("0")) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash cannot be negative")
        self._cash = initial_cash
        self._cumulative_fees = Decimal("0")
        self._realized_pnl = Decimal("0")
        self._positions: dict[str, PositionAccounting] = {}
        self._fill_ids: set[str] = set()

    def apply_fill(
        self,
        *,
        fill_id: str,
        instrument: str,
        signed_quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
    ) -> PositionAccounting:
        fill_id = str(fill_id).strip()
        instrument = str(instrument).strip()
        if not fill_id or not instrument:
            raise ValueError("fill_id and instrument are required")
        if fill_id in self._fill_ids:
            raise DuplicateFillError(f"duplicate fill_id: {fill_id}")
        if signed_quantity == 0:
            raise ValueError("signed_quantity cannot be zero")
        if price <= 0 or fee < 0:
            raise ValueError("price must be positive and fee non-negative")

        current = self._positions.get(instrument, PositionAccounting())
        q0 = current.quantity
        qf = signed_quantity
        q1 = q0 + qf
        realized_delta = Decimal("0")

        if q0 == 0 or (q0 > 0 and qf > 0) or (q0 < 0 and qf < 0):
            total_abs = abs(q0) + abs(qf)
            if q0 == 0:
                average = price
            else:
                average = (
                    abs(q0) * current.average_price + abs(qf) * price
                ) / total_abs
        else:
            closed = min(abs(q0), abs(qf))
            direction = Decimal("1") if q0 > 0 else Decimal("-1")
            realized_delta = closed * (price - current.average_price) * direction

            if q1 == 0:
                average = Decimal("0")
            elif (q1 > 0) == (q0 > 0):
                average = current.average_price
            else:
                # The fill crossed through flat; the residual position opened at
                # this fill price.
                average = price

        updated = PositionAccounting(
            quantity=q1,
            average_price=average,
            realized_pnl=current.realized_pnl + realized_delta,
        )

        self._cash -= qf * price
        self._cash -= fee
        self._cumulative_fees += fee
        self._realized_pnl += realized_delta
        self._fill_ids.add(fill_id)
        if q1 == 0:
            self._positions.pop(instrument, None)
        else:
            self._positions[instrument] = updated
        return updated

    def snapshot(self) -> PortfolioAccountingSnapshot:
        positions = dict(self._positions)
        return PortfolioAccountingSnapshot(
            cash=self._cash,
            cumulative_fees=self._cumulative_fees,
            realized_pnl=self._realized_pnl,
            positions=positions,
            applied_fill_ids=tuple(sorted(self._fill_ids)),
        )

    def mark_to_market(
        self,
        marks: Mapping[str, Decimal],
    ) -> MarkToMarketSnapshot:
        missing = set(self._positions) - set(marks)
        if missing:
            raise ValueError("missing marks for: " + ",".join(sorted(missing)))

        market_value = Decimal("0")
        gross = Decimal("0")
        unrealized = Decimal("0")
        for instrument, position in self._positions.items():
            mark = marks[instrument]
            if mark <= 0:
                raise ValueError(f"mark must be positive: {instrument}")
            notional = position.quantity * mark
            market_value += notional
            gross += abs(notional)
            unrealized += position.quantity * (mark - position.average_price)

        snapshot = self.snapshot()
        return MarkToMarketSnapshot(
            cash=snapshot.cash,
            market_value=market_value,
            equity=snapshot.cash + market_value,
            gross_exposure=gross,
            unrealized_pnl=unrealized,
            realized_pnl=snapshot.realized_pnl,
            cumulative_fees=snapshot.cumulative_fees,
        )

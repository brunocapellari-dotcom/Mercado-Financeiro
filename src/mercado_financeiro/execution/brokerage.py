from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from mercado_financeiro.risk import OrderIntent


class SettlementCalendar(Protocol):
    """Calendar boundary used to resolve contractual settlement dates."""

    verified: bool

    def add_business_days(self, timestamp: datetime, business_days: int) -> datetime:
        ...


@dataclass(frozen=True)
class BrokerageCostSchedule:
    """Explicit execution-cost parameters.

    Values are configuration, never silently inferred from a current broker fee
    page. Production research must persist the schedule/version used by each run.
    """

    fee_bps: Decimal
    fixed_fee: Decimal = Decimal("0")
    minimum_fee: Decimal = Decimal("0")
    base_slippage_bps: Decimal = Decimal("0")
    impact_bps_per_adv_fraction: Decimal = Decimal("0")
    max_adv_participation: Decimal = Decimal("0.05")
    settlement_business_days: int = 2
    allow_partial_fills: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("fee_bps", self.fee_bps),
            ("fixed_fee", self.fixed_fee),
            ("minimum_fee", self.minimum_fee),
            ("base_slippage_bps", self.base_slippage_bps),
            ("impact_bps_per_adv_fraction", self.impact_bps_per_adv_fraction),
            ("max_adv_participation", self.max_adv_participation),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.max_adv_participation <= 0 or self.max_adv_participation > 1:
            raise ValueError("max_adv_participation must be in (0, 1]")
        if self.settlement_business_days < 0:
            raise ValueError("settlement_business_days cannot be negative")


@dataclass(frozen=True)
class MarketExecutionState:
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    available_quantity: Decimal
    adv_notional: Decimal
    stale: bool = False
    trading_open: bool = True

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("invalid bid/ask")
        if self.available_quantity < 0 or self.adv_notional < 0:
            raise ValueError("liquidity values cannot be negative")


@dataclass(frozen=True)
class SimulatedFill:
    filled: bool
    reason: str
    quantity: Decimal
    fill_price: Decimal | None
    fee: Decimal
    slippage_bps: Decimal
    settlement_date: datetime | None
    cash_delta: Decimal


class DeterministicBrokerageModel:
    """Shared backtest/paper execution semantics for a configured brokerage.

    This intentionally models a marketable order conservatively from bid/ask,
    explicit slippage/impact and explicit fees. It is not a claim that these
    parameters match any broker until that broker schedule has been audited.
    Contractual settlement requires an externally supplied, verified calendar;
    it is never approximated with simple calendar-day arithmetic.
    """

    def __init__(
        self,
        schedule: BrokerageCostSchedule,
        *,
        settlement_calendar: SettlementCalendar | None = None,
    ) -> None:
        self._schedule = schedule
        self._settlement_calendar = settlement_calendar

    @property
    def schedule(self) -> BrokerageCostSchedule:
        return self._schedule

    def simulate_market_order(
        self,
        order: OrderIntent,
        market: MarketExecutionState,
        *,
        cash_available: Decimal,
    ) -> SimulatedFill:
        if cash_available < 0:
            raise ValueError("cash_available cannot be negative")
        if market.stale:
            return self._rejected("stale_market_data")
        if not market.trading_open:
            return self._rejected("market_closed")
        if market.available_quantity <= 0:
            return self._rejected("insufficient_visible_liquidity")

        fill_quantity = order.quantity
        partial = False
        if order.quantity > market.available_quantity:
            if not self._schedule.allow_partial_fills:
                return self._rejected("insufficient_visible_liquidity")
            fill_quantity = market.available_quantity
            partial = True

        if market.adv_notional <= 0:
            return self._rejected("adv_unavailable")
        if self._schedule.settlement_business_days > 0:
            calendar = self._settlement_calendar
            if calendar is None or not bool(getattr(calendar, "verified", False)):
                return self._rejected("verified_settlement_calendar_unavailable")

        reference = market.ask if order.side == "buy" else market.bid
        reference_notional = reference * fill_quantity
        participation = reference_notional / market.adv_notional
        if participation > self._schedule.max_adv_participation:
            return self._rejected("max_adv_participation_exceeded")

        slip_bps = (
            self._schedule.base_slippage_bps
            + self._schedule.impact_bps_per_adv_fraction * participation
        )
        slip_fraction = slip_bps / Decimal("10000")
        if order.side == "buy":
            fill_price = reference * (Decimal("1") + slip_fraction)
        else:
            fill_price = reference * (Decimal("1") - slip_fraction)
        if fill_price <= 0:
            return self._rejected("invalid_simulated_fill_price")

        gross = fill_price * fill_quantity
        fee = max(
            self._schedule.minimum_fee,
            self._schedule.fixed_fee + gross * self._schedule.fee_bps / Decimal("10000"),
        )
        if order.side == "buy" and gross + fee > cash_available:
            return self._rejected("insufficient_buying_power")

        cash_delta = -(gross + fee) if order.side == "buy" else gross - fee
        if self._schedule.settlement_business_days:
            assert self._settlement_calendar is not None
            settlement = self._settlement_calendar.add_business_days(
                market.timestamp, self._schedule.settlement_business_days
            )
        else:
            settlement = market.timestamp
        return SimulatedFill(
            filled=True,
            reason="partial_fill" if partial else "filled",
            quantity=fill_quantity,
            fill_price=fill_price,
            fee=fee,
            slippage_bps=slip_bps,
            settlement_date=settlement,
            cash_delta=cash_delta,
        )

    @staticmethod
    def _rejected(reason: str) -> SimulatedFill:
        return SimulatedFill(
            filled=False,
            reason=reason,
            quantity=Decimal("0"),
            fill_price=None,
            fee=Decimal("0"),
            slippage_bps=Decimal("0"),
            settlement_date=None,
            cash_delta=Decimal("0"),
        )

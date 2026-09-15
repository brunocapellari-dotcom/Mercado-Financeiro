from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional: Decimal
    max_abs_position: Decimal
    allowed_instruments: frozenset[str]
    trading_start: time
    trading_end: time
    trading_timezone: str = "America/Sao_Paulo"
    max_drawdown_fraction: Decimal = Decimal("0.10")
    max_daily_loss: Decimal = Decimal("0")
    max_adv_participation: Decimal = Decimal("0.05")
    max_market_data_age_seconds: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        positive_fields = {
            "max_order_notional": self.max_order_notional,
            "max_abs_position": self.max_abs_position,
            "max_drawdown_fraction": self.max_drawdown_fraction,
            "max_adv_participation": self.max_adv_participation,
            "max_market_data_age_seconds": self.max_market_data_age_seconds,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_daily_loss < 0:
            raise ValueError("max_daily_loss must be non-negative")
        if not self.allowed_instruments:
            raise ValueError("allowed_instruments must not be empty")
        ZoneInfo(self.trading_timezone)


@dataclass(frozen=True)
class OrderIntent:
    instrument: str
    side: str
    quantity: Decimal
    price: Decimal
    signal_id: str
    idempotency_key: str
    created_at: datetime

    def __post_init__(self) -> None:
        side = self.side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        object.__setattr__(self, "side", side)
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.price


@dataclass(frozen=True)
class RiskContext:
    current_position: Decimal
    equity: Decimal
    peak_equity: Decimal
    pnl_today: Decimal
    adv_notional: Decimal
    market_data_age_seconds: Decimal
    now: datetime
    kill_switch_engaged: bool = False

    def __post_init__(self) -> None:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if self.equity < 0 or self.peak_equity < 0:
            raise ValueError("equity values cannot be negative")
        if self.adv_notional < 0:
            raise ValueError("adv_notional cannot be negative")
        if self.market_data_age_seconds < 0:
            raise ValueError("market_data_age_seconds cannot be negative")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    projected_position: Decimal
    order_notional: Decimal


class DeterministicRiskEngine:
    """Fail-closed pre-trade risk engine with no LLM/model dependency."""

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    def evaluate(self, order: OrderIntent, context: RiskContext) -> RiskDecision:
        reasons: list[str] = []
        signed_qty = order.quantity if order.side == "buy" else -order.quantity
        projected_position = context.current_position + signed_qty
        notional = order.notional

        if context.kill_switch_engaged:
            reasons.append("kill_switch_engaged")

        if order.instrument not in self._limits.allowed_instruments:
            reasons.append("instrument_not_allowed")

        local_now = context.now.astimezone(ZoneInfo(self._limits.trading_timezone)).timetz().replace(tzinfo=None)
        if not self._within_trading_window(local_now):
            reasons.append("outside_trading_hours")

        if notional > self._limits.max_order_notional:
            reasons.append("max_order_notional_exceeded")

        if abs(projected_position) > self._limits.max_abs_position:
            reasons.append("max_position_exceeded")

        if context.peak_equity > 0:
            drawdown = max(Decimal("0"), (context.peak_equity - context.equity) / context.peak_equity)
            if drawdown > self._limits.max_drawdown_fraction:
                reasons.append("max_drawdown_exceeded")

        if context.pnl_today < -self._limits.max_daily_loss:
            reasons.append("max_daily_loss_exceeded")

        if context.market_data_age_seconds > self._limits.max_market_data_age_seconds:
            reasons.append("stale_market_data")

        if context.adv_notional <= 0:
            reasons.append("liquidity_unavailable")
        elif notional > context.adv_notional * self._limits.max_adv_participation:
            reasons.append("liquidity_limit_exceeded")

        return RiskDecision(
            approved=not reasons,
            reasons=tuple(reasons),
            projected_position=projected_position,
            order_notional=notional,
        )

    def _within_trading_window(self, current: time) -> bool:
        start = self._limits.trading_start
        end = self._limits.trading_end
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

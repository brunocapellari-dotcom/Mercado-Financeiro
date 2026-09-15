from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mercado_financeiro.execution import (
    BrokerageCostSchedule,
    DeterministicBrokerageModel,
    MarketExecutionState,
)
from mercado_financeiro.risk import OrderIntent


class VerifiedCalendar:
    verified = True

    def add_business_days(self, timestamp: datetime, business_days: int) -> datetime:
        current = timestamp
        remaining = business_days
        while remaining:
            current += timedelta(days=1)
            if current.weekday() < 5:
                remaining -= 1
        return current


def _order(*, side: str = "buy", quantity: str = "100") -> OrderIntent:
    return OrderIntent(
        instrument="PETR4",
        side=side,
        quantity=Decimal(quantity),
        price=Decimal("10"),
        signal_id="sig",
        idempotency_key=f"{side}-{quantity}",
        created_at=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
    )


def _market(**overrides) -> MarketExecutionState:
    values = {
        "timestamp": datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
        "bid": Decimal("9.99"),
        "ask": Decimal("10.01"),
        "available_quantity": Decimal("10000"),
        "adv_notional": Decimal("1000000"),
        "stale": False,
        "trading_open": True,
    }
    values.update(overrides)
    return MarketExecutionState(**values)


def _model(*, calendar=True) -> DeterministicBrokerageModel:
    schedule = BrokerageCostSchedule(
        fee_bps=Decimal("2"),
        fixed_fee=Decimal("1"),
        minimum_fee=Decimal("1"),
        base_slippage_bps=Decimal("5"),
        impact_bps_per_adv_fraction=Decimal("100"),
        max_adv_participation=Decimal("0.05"),
        settlement_business_days=2,
    )
    return DeterministicBrokerageModel(
        schedule,
        settlement_calendar=VerifiedCalendar() if calendar else None,
    )


def test_cost_model_is_adverse_and_explicit():
    fill = _model().simulate_market_order(
        _order(), _market(), cash_available=Decimal("100000")
    )
    assert fill.filled
    assert fill.fill_price is not None and fill.fill_price > Decimal("10.01")
    assert fill.fee >= Decimal("1")
    assert fill.slippage_bps > Decimal("5")
    assert fill.cash_delta < 0
    assert fill.settlement_date is not None


def test_model_blocks_stale_liquidity_and_buying_power():
    model = _model()
    assert model.simulate_market_order(
        _order(), _market(stale=True), cash_available=Decimal("100000")
    ).reason == "stale_market_data"
    assert model.simulate_market_order(
        _order(quantity="20000"), _market(), cash_available=Decimal("1000000")
    ).reason == "insufficient_visible_liquidity"
    assert model.simulate_market_order(
        _order(), _market(), cash_available=Decimal("10")
    ).reason == "insufficient_buying_power"


def test_unverified_settlement_calendar_fails_closed():
    fill = _model(calendar=False).simulate_market_order(
        _order(), _market(), cash_available=Decimal("100000")
    )
    assert not fill.filled
    assert fill.reason == "verified_settlement_calendar_unavailable"

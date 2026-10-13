from datetime import datetime, timezone
from decimal import Decimal

from mercado_financeiro.execution import (
    BrokerageCostSchedule,
    DeterministicBrokerageModel,
    MarketExecutionState,
)
from mercado_financeiro.risk import OrderIntent


def test_partial_fill_is_opt_in_and_uses_available_quantity():
    model = DeterministicBrokerageModel(
        BrokerageCostSchedule(
            fee_bps=Decimal("2"),
            base_slippage_bps=Decimal("5"),
            impact_bps_per_adv_fraction=Decimal("10"),
            max_adv_participation=Decimal("0.05"),
            settlement_business_days=0,
            allow_partial_fills=True,
        )
    )
    order = OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("30"),
        signal_id="sig-partial",
        idempotency_key="partial-1",
        created_at=datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc),
    )
    market = MarketExecutionState(
        timestamp=datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc),
        bid=Decimal("29.99"),
        ask=Decimal("30.01"),
        available_quantity=Decimal("40"),
        adv_notional=Decimal("10000000"),
    )

    fill = model.simulate_market_order(
        order,
        market,
        cash_available=Decimal("100000"),
    )
    assert fill.filled
    assert fill.reason == "partial_fill"
    assert fill.quantity == Decimal("40")
    assert fill.fill_price is not None


def test_partial_fill_remains_disabled_by_default():
    model = DeterministicBrokerageModel(
        BrokerageCostSchedule(
            fee_bps=Decimal("0"),
            settlement_business_days=0,
        )
    )
    order = OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("30"),
        signal_id="sig-no-partial",
        idempotency_key="partial-disabled",
        created_at=datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc),
    )
    market = MarketExecutionState(
        timestamp=datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc),
        bid=Decimal("29.99"),
        ask=Decimal("30.01"),
        available_quantity=Decimal("40"),
        adv_notional=Decimal("10000000"),
    )

    fill = model.simulate_market_order(
        order,
        market,
        cash_available=Decimal("100000"),
    )
    assert not fill.filled
    assert fill.reason == "insufficient_visible_liquidity"

from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from mercado_financeiro.execution import BrokerOrderAck, DeterministicExecutionEngine
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskContext, RiskLimits
from mercado_financeiro.runtime import InMemoryEventBus, RuntimeMode, TradingKernel


class FakeBroker:
    def __init__(self) -> None:
        self.calls = 0

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        self.calls += 1
        return BrokerOrderAck(accepted=True, broker_order_id=f"B-{self.calls}", status="accepted")


def _execution() -> tuple[DeterministicExecutionEngine, FakeBroker]:
    broker = FakeBroker()
    limits = RiskLimits(
        max_order_notional=Decimal("100000"),
        max_abs_position=Decimal("10000"),
        allowed_instruments=frozenset({"PETR4"}),
        trading_start=time(10, 0),
        trading_end=time(18, 0),
        max_daily_loss=Decimal("1000"),
    )
    return DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(limits), broker=broker
    ), broker


def _order() -> OrderIntent:
    return OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("10"),
        signal_id="sig-1",
        idempotency_key="order-1",
        created_at=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
    )


def _context(*, killed: bool = False) -> RiskContext:
    return RiskContext(
        current_position=Decimal("0"),
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        pnl_today=Decimal("0"),
        adv_notional=Decimal("1000000"),
        market_data_age_seconds=Decimal("1"),
        now=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
        kill_switch_engaged=killed,
    )


def test_kernel_uses_same_risk_execution_path_and_publishes_events():
    execution, broker = _execution()
    bus = InMemoryEventBus()
    topics: list[str] = []
    bus.subscribe("orders.intent", lambda event: topics.append(event.topic))
    bus.subscribe("orders.result", lambda event: topics.append(event.topic))
    kernel = TradingKernel(mode=RuntimeMode.PAPER, event_bus=bus, execution_engine=execution)

    result = kernel.submit_order(_order(), _context())
    assert result.result.accepted
    assert broker.calls == 1
    assert topics == ["orders.intent", "orders.result"]


def test_kernel_cannot_bypass_risk():
    execution, broker = _execution()
    kernel = TradingKernel(
        mode=RuntimeMode.BACKTEST,
        event_bus=InMemoryEventBus(),
        execution_engine=execution,
    )
    result = kernel.submit_order(_order(), _context(killed=True))
    assert not result.result.accepted
    assert broker.calls == 0


def test_live_rejects_non_durable_event_bus():
    execution, _ = _execution()
    with pytest.raises(RuntimeError, match="live-safe event bus"):
        TradingKernel(
            mode=RuntimeMode.LIVE,
            event_bus=InMemoryEventBus(),
            execution_engine=execution,
        )

from datetime import datetime, time, timezone
from decimal import Decimal

from mercado_financeiro.execution import (
    BrokerOrderAck,
    BrokerSubmissionOutcomeUnknown,
    DeterministicExecutionEngine,
)
from mercado_financeiro.risk import (
    DeterministicRiskEngine,
    InMemoryKillSwitch,
    OrderIntent,
    RiskContext,
    RiskLimits,
)


class CountingBroker:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.calls = 0
        self.ambiguous = ambiguous

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        self.calls += 1
        if self.ambiguous:
            raise BrokerSubmissionOutcomeUnknown("timeout after send")
        return BrokerOrderAck(accepted=True, broker_order_id=f"B-{self.calls}", status="accepted")


def _risk() -> DeterministicRiskEngine:
    return DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=Decimal("100000"),
            max_abs_position=Decimal("10000"),
            allowed_instruments=frozenset({"PETR4"}),
            trading_start=time(10, 0),
            trading_end=time(18, 0),
            max_daily_loss=Decimal("1000"),
        )
    )


def _order(key: str = "order-1") -> OrderIntent:
    return OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("10"),
        signal_id="sig-1",
        idempotency_key=key,
        created_at=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
    )


def _context() -> RiskContext:
    return RiskContext(
        current_position=Decimal("0"),
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        pnl_today=Decimal("0"),
        adv_notional=Decimal("1000000"),
        market_data_age_seconds=Decimal("1"),
        now=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
    )


def test_independent_kill_switch_is_read_inside_execution_boundary():
    broker = CountingBroker()
    switch = InMemoryKillSwitch()
    switch.engage("operator emergency")
    engine = DeterministicExecutionEngine(
        risk_engine=_risk(),
        broker=broker,
        kill_switch=switch,
    )
    result = engine.execute(_order(), _context())
    assert result.accepted is False
    assert "kill_switch_engaged" in result.risk_reasons
    assert broker.calls == 0
    assert engine.kill_switch_live_safe is False


def test_ambiguous_submission_is_never_blindly_retried():
    broker = CountingBroker(ambiguous=True)
    engine = DeterministicExecutionEngine(risk_engine=_risk(), broker=broker)
    first = engine.execute(_order("ambiguous-1"), _context())
    second = engine.execute(_order("ambiguous-1"), _context())

    assert first.accepted is None
    assert first.status == "submission_ambiguous"
    assert first.requires_reconciliation
    assert broker.calls == 1
    assert second.duplicate
    assert second.requires_reconciliation
    assert second.status == "submission_ambiguous"

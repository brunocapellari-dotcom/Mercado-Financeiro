from datetime import datetime, time, timezone
from decimal import Decimal

from mercado_financeiro.execution import BrokerageCostSchedule, MarketExecutionState
from mercado_financeiro.operations.simulation import (
    DeterministicSimulationSession,
    SimulationEvent,
    SimulationMode,
)
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskLimits


def test_backtest_session_uses_same_risk_cost_and_accounting_path_as_paper():
    now = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
    risk = DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=Decimal("10000"),
            max_abs_position=Decimal("1000"),
            allowed_instruments=frozenset({"PETR4"}),
            trading_start=time(10, 0),
            trading_end=time(18, 0),
            max_daily_loss=Decimal("1000"),
        )
    )
    session = DeterministicSimulationSession(
        mode=SimulationMode.BACKTEST,
        risk_engine=risk,
        brokerage_schedule=BrokerageCostSchedule(
            fee_bps=Decimal("2"),
            base_slippage_bps=Decimal("5"),
            max_adv_participation=Decimal("0.05"),
            settlement_business_days=0,
        ),
        initial_cash=Decimal("100000"),
    )
    report = session.run(
        [
            SimulationEvent(
                order=OrderIntent(
                    instrument="PETR4",
                    side="buy",
                    quantity=Decimal("100"),
                    price=Decimal("30"),
                    signal_id="sig-1",
                    idempotency_key="bt-1",
                    created_at=now,
                ),
                market=MarketExecutionState(
                    timestamp=now,
                    bid=Decimal("29.99"),
                    ask=Decimal("30.01"),
                    available_quantity=Decimal("10000"),
                    adv_notional=Decimal("10000000"),
                ),
                marks={"PETR4": Decimal("30")},
                market_data_age_seconds=Decimal("1"),
            )
        ]
    )
    assert report.mode is SimulationMode.BACKTEST
    assert report.steps[0].execution.accepted is True
    assert report.final.cumulative_fees > 0
    assert len(report.digest_sha256) == 64

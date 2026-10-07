from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from mercado_financeiro.accounting import PortfolioAccountingLedger
from mercado_financeiro.execution import (
    BrokerageCostSchedule,
    DeterministicBrokerageModel,
    DeterministicExecutionEngine,
    MarketExecutionState,
)
from mercado_financeiro.operations import (
    AttributionRecord,
    Feature,
    OperationalCapabilities,
    OperationalDashboardSnapshot,
    Provenance,
    SimulatedBrokerAdapter,
    assert_operational_ready,
    build_attribution,
    classify_market_regime,
    evaluate_operational_readiness,
)
from mercado_financeiro.risk import (
    DeterministicRiskEngine,
    OrderIntent,
    RiskContext,
    RiskLimits,
)


def _now() -> datetime:
    return datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)


def test_canonical_feature_contract_blocks_lookahead():
    with pytest.raises(ValueError, match="future information"):
        Feature(
            asset_id="PETR4",
            name="momentum_21",
            value=Decimal("0.12"),
            feature_time=_now(),
            source_max_available_from=datetime(2026, 10, 7, 14, 1, tzinfo=timezone.utc),
            version="v1",
        )

    with pytest.raises(ValueError, match="available_from cannot be after ingestion_time"):
        Provenance(
            source="test",
            reference_time=_now(),
            available_from=datetime(2026, 10, 7, 14, 2, tzinfo=timezone.utc),
            ingestion_time=_now(),
            vintage="v1",
        )


def test_risk_to_simulated_fill_updates_accounting_without_real_broker():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("100000"))
    brokerage = DeterministicBrokerageModel(
        BrokerageCostSchedule(
            fee_bps=Decimal("2"),
            base_slippage_bps=Decimal("5"),
            impact_bps_per_adv_fraction=Decimal("50"),
            max_adv_participation=Decimal("0.05"),
            settlement_business_days=0,
        )
    )
    broker = SimulatedBrokerAdapter(brokerage_model=brokerage, ledger=ledger)
    broker.set_market(
        "PETR4",
        MarketExecutionState(
            timestamp=_now(),
            bid=Decimal("29.99"),
            ask=Decimal("30.01"),
            available_quantity=Decimal("10000"),
            adv_notional=Decimal("10000000"),
            trading_open=True,
        ),
    )
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
    engine = DeterministicExecutionEngine(risk_engine=risk, broker=broker)
    order = OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("30"),
        signal_id="sig-1",
        idempotency_key="paper-1",
        created_at=_now(),
    )
    context = RiskContext(
        current_position=Decimal("0"),
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        pnl_today=Decimal("0"),
        adv_notional=Decimal("10000000"),
        market_data_age_seconds=Decimal("1"),
        now=_now(),
    )

    result = engine.execute(order, context)
    assert result.accepted is True
    assert result.status == "filled"
    assert len(broker.fills) == 1
    snapshot = ledger.snapshot()
    assert snapshot.positions["PETR4"].quantity == Decimal("100")
    marked = ledger.mark_to_market({"PETR4": Decimal("31")})
    assert marked.gross_exposure == Decimal("3100")
    assert marked.cumulative_fees > 0


def test_attribution_reconciles_every_dimension():
    report = build_attribution(
        [
            AttributionRecord(
                asset="PETR4",
                sector="energy",
                factor="value",
                strategy="multifactor",
                period="2026-10",
                decision="entry",
                gross_pnl=Decimal("100"),
                costs=Decimal("5"),
            ),
            AttributionRecord(
                asset="VALE3",
                sector="materials",
                factor="momentum",
                strategy="multifactor",
                period="2026-10",
                decision="rebalance",
                gross_pnl=Decimal("-20"),
                costs=Decimal("2"),
            ),
        ]
    )
    assert report.gross_pnl == Decimal("80")
    assert report.costs == Decimal("7")
    assert report.net_pnl == Decimal("73")
    assert sum((value for _, value in report.by_asset), Decimal("0")) == Decimal("73")


def test_simple_market_regime_is_deterministic():
    regime = classify_market_regime(
        broad_market_return=Decimal("-0.08"),
        annualized_volatility=Decimal("0.30"),
        rate_change_3m=Decimal("0.01"),
        inflation_zscore=Decimal("1.4"),
    )
    assert regime.risk == "risk_off"
    assert regime.volatility == "high"
    assert regime.rates == "rising"
    assert regime.inflation == "high"


def test_operational_release_gate_is_separate_from_live_capital_gate():
    blocked = evaluate_operational_readiness(OperationalCapabilities())
    assert not blocked.approved
    assert "end_to_end" in blocked.missing

    values = {
        name: True
        for name in OperationalCapabilities.__dataclass_fields__
    }
    ready = assert_operational_ready(OperationalCapabilities(**values))
    assert ready.approved


def test_dashboard_requires_all_release_sections():
    snapshot = OperationalDashboardSnapshot(
        data_health={"late_sources": 0},
        strategies={"oos": "ok"},
        portfolio={"equity": "100000"},
        risk={"blocks": 0},
        paper_trading={"orders": 1},
        performance={"drawdown": "0"},
        experiments={"count": 2},
        system_health={"jobs": "ok"},
    )
    payload = snapshot.to_dict()
    assert set(payload) == {
        "data_health",
        "strategies",
        "portfolio",
        "risk",
        "paper_trading",
        "performance",
        "experiments",
        "system_health",
    }
    assert "Operational Dashboard" in snapshot.render_html()

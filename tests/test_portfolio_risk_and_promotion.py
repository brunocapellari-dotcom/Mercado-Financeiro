from decimal import Decimal

import pytest

from mercado_financeiro.architecture import (
    DeploymentStage,
    assert_stage_promotion,
    evaluate_stage_promotion,
)
from mercado_financeiro.risk import (
    DeterministicPortfolioRiskEngine,
    PortfolioRiskLimits,
    PortfolioRiskSnapshot,
)


def test_portfolio_risk_vetoes_concentration_beta_factor_and_capacity():
    engine = DeterministicPortfolioRiskEngine(
        PortfolioRiskLimits(
            max_gross_exposure_fraction=Decimal("1.0"),
            max_abs_net_exposure_fraction=Decimal("0.5"),
            max_sector_exposure_fraction=Decimal("0.25"),
            max_abs_beta=Decimal("1.5"),
            max_abs_factor_exposure=Decimal("2.0"),
            max_correlation_cluster_fraction=Decimal("0.3"),
            max_capacity_utilization=Decimal("0.8"),
        )
    )
    snapshot = PortfolioRiskSnapshot(
        equity=Decimal("100000"),
        gross_notional=Decimal("120000"),
        net_notional=Decimal("60000"),
        sector_notionals={"energy": Decimal("30000")},
        factor_exposures={"momentum": Decimal("2.5")},
        beta=Decimal("1.8"),
        largest_correlation_cluster_notional=Decimal("40000"),
        capacity_utilization=Decimal("0.9"),
    )
    result = engine.evaluate(snapshot)
    assert not result.approved
    assert "max_gross_exposure_exceeded" in result.reasons
    assert "max_net_exposure_exceeded" in result.reasons
    assert "max_sector_exposure_exceeded" in result.reasons
    assert "max_beta_exceeded" in result.reasons
    assert "factor_exposure_exceeded:momentum" in result.reasons
    assert "max_correlation_cluster_exceeded" in result.reasons
    assert "capacity_limit_exceeded" in result.reasons


def test_promotion_must_be_adjacent_and_evidence_gated():
    skipped = evaluate_stage_promotion(
        DeploymentStage.RESEARCH,
        DeploymentStage.PAPER,
        {"walk_forward": True},
    )
    assert not skipped.approved
    assert skipped.reason == "promotion_must_be_adjacent_and_forward"

    blocked = evaluate_stage_promotion(
        DeploymentStage.RESEARCH,
        DeploymentStage.BACKTEST,
        {"historical_data_gate": True, "source_integrity": False},
    )
    assert not blocked.approved
    assert blocked.failed == ("source_integrity",)

    approved = assert_stage_promotion(
        DeploymentStage.RESEARCH,
        DeploymentStage.BACKTEST,
        {"historical_data_gate": True, "source_integrity": True},
    )
    assert approved.approved


def test_live_promotion_never_bypasses_mandatory_gates():
    evidence = {
        "backtest": True,
        "walk_forward": True,
        "paper": True,
        "shadow": True,
        "reconciliation": True,
        "security_test": True,
        "risk_validation": False,
    }
    result = evaluate_stage_promotion(DeploymentStage.SHADOW, DeploymentStage.LIVE, evidence)
    assert not result.approved
    assert result.failed == ("risk_validation",)
    with pytest.raises(RuntimeError):
        assert_stage_promotion(DeploymentStage.SHADOW, DeploymentStage.LIVE, evidence)

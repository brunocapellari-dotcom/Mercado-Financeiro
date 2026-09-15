import pytest

from mercado_financeiro.architecture import (
    AuditDomain,
    PipelineStage,
    REQUIRED_LIVE_GATES,
    assert_pipeline_transition,
    evaluate_live_promotion,
)


def test_pipeline_allows_only_adjacent_stages():
    assert_pipeline_transition(PipelineStage.DATA, PipelineStage.INTELLIGENCE)
    assert_pipeline_transition(PipelineStage.RISK, PipelineStage.EXECUTION)

    with pytest.raises(ValueError):
        assert_pipeline_transition(PipelineStage.DATA, PipelineStage.SIGNAL)
    with pytest.raises(ValueError):
        assert_pipeline_transition(PipelineStage.SIGNAL, PipelineStage.EXECUTION)


def test_live_promotion_fails_closed_on_missing_or_failed_gate():
    all_green = {name: True for name in REQUIRED_LIVE_GATES}
    assert evaluate_live_promotion(all_green).approved is True

    missing = dict(all_green)
    missing.pop("shadow")
    result = evaluate_live_promotion(missing)
    assert result.approved is False
    assert "shadow" in result.missing

    failed = dict(all_green)
    failed["security_test"] = False
    result = evaluate_live_promotion(failed)
    assert result.approved is False
    assert "security_test" in result.failed


def test_required_audit_domains_cover_operational_stack():
    expected = {
        "market_data", "news", "fundamentals", "macro", "b3", "cvm", "bcb",
        "anbima", "nefin", "backtests", "vintages", "broker", "risk", "execution",
        "paper", "shadow", "live", "logs", "reconciliation",
    }
    assert {domain.value for domain in AuditDomain} == expected

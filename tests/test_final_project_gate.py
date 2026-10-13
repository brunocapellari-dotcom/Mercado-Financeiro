from dataclasses import fields

import pytest

from mercado_financeiro.architecture import (
    FinalProjectCapabilities,
    assert_final_project_ready,
    evaluate_final_project_readiness,
)


def test_final_project_gate_fails_closed_by_default():
    result = evaluate_final_project_readiness(FinalProjectCapabilities())
    assert not result.approved
    assert "static_quality_gate" in result.missing
    assert "historical_identity_2011_2026" in result.missing
    assert "cvm_fund_flows_pit" in result.missing
    assert "cvm_fund_holdings_pit" in result.missing
    assert "tournament_walk_forward_oos" in result.missing
    assert "security_red_team_validated" in result.missing
    with pytest.raises(RuntimeError, match="final project gate blocked"):
        assert_final_project_ready(FinalProjectCapabilities())


def test_final_project_gate_requires_every_capability():
    values = {field.name: True for field in fields(FinalProjectCapabilities)}
    capabilities = FinalProjectCapabilities(**values)
    result = assert_final_project_ready(capabilities)
    assert result.approved
    assert result.missing == ()

from decimal import Decimal
from types import SimpleNamespace

import pytest

from mercado_financeiro.agents import (
    AgentSpendLedger,
    PydanticHarnessProfile,
    ResearchArtifact,
    ResearchToolPolicy,
    SpendLimitExceeded,
    ToolDecision,
    missing_harness_capabilities,
)


def test_research_tool_policy_is_fail_closed_and_blocks_execution_paths():
    policy = ResearchToolPolicy(
        allowed_tools=frozenset({"research.web", "data.read"}),
        approval_required_tools=frozenset({"research.download"}),
    )
    assert policy.decide("research.web") is ToolDecision.ALLOW
    assert policy.decide("research.download") is ToolDecision.REQUIRE_APPROVAL
    assert policy.decide("unknown.tool") is ToolDecision.DENY
    assert policy.decide("broker.submit_order") is ToolDecision.DENY
    assert policy.decide("risk.limit.update") is ToolDecision.DENY
    assert policy.decide("kill_switch.disable") is ToolDecision.DENY
    assert policy.decide("live.promote") is ToolDecision.DENY


def test_spend_ledger_fails_before_mutating_state():
    ledger = AgentSpendLedger(
        max_cost_usd=Decimal("1.00"),
        max_input_tokens=1000,
        max_output_tokens=500,
    )
    ledger.reserve(cost_usd="0.25", input_tokens=100, output_tokens=50)
    with pytest.raises(SpendLimitExceeded, match="cost_usd"):
        ledger.reserve(cost_usd="0.80", input_tokens=10, output_tokens=10)
    assert ledger.cost_usd == Decimal("0.25")
    assert ledger.input_tokens == 100
    assert ledger.output_tokens == 50


def test_research_artifact_requires_evidence_and_is_hypothesis_only():
    artifact = ResearchArtifact(
        artifact_id="hyp-1",
        hypothesis="Value spread may predict future cross-sectional returns.",
        evidence_refs=("NEFIN:2026-09-18",),
        uncertainty="high",
        generated_by="quant-research-agent",
    )
    assert artifact.evidence_refs
    with pytest.raises(ValueError, match="evidence_refs"):
        ResearchArtifact(
            artifact_id="hyp-2",
            hypothesis="unsupported",
            evidence_refs=(),
            uncertainty="high",
            generated_by="agent",
        )


def test_harness_capability_check_is_adapter_based_not_version_coupled():
    complete = SimpleNamespace(
        Planning=object(),
        SubAgents=object(),
        Memory=object(),
        SpendLimits=object(),
        TrajectoryJudge=object(),
        DynamicWorkflow=object(),
    )
    assert missing_harness_capabilities(complete, PydanticHarnessProfile()) == ()

    incomplete = SimpleNamespace(Planning=object())
    missing = missing_harness_capabilities(incomplete)
    assert "SubAgents" in missing
    assert "TrajectoryJudge" in missing

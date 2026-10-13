from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class BenchmarkRole(str, Enum):
    CANONICAL = "canonical"
    RESEARCH_BENCHMARK = "research_benchmark"
    RUNTIME_CANDIDATE = "runtime_candidate"
    INDEPENDENT_REFERENCE = "independent_reference"
    OPTIMIZER_BENCHMARK = "optimizer_benchmark"


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    role: BenchmarkRole
    current_line: str
    allowed_capabilities: frozenset[str]
    financial_authority: bool
    real_capital_allowed: bool
    rationale: str


TOOL_POLICY: Mapping[str, ToolPolicy] = {
    "internal": ToolPolicy(
        name="Mercado Financeiro deterministic core",
        role=BenchmarkRole.CANONICAL,
        current_line="repository-owned",
        allowed_capabilities=frozenset(
            {"pit", "research", "backtest", "risk", "accounting", "paper", "shadow", "execution"}
        ),
        financial_authority=True,
        real_capital_allowed=False,
        rationale="Canonical PIT, risk, accounting and execution contracts remain project-owned.",
    ),
    "vectorbt": ToolPolicy(
        name="VectorBT",
        role=BenchmarkRole.RESEARCH_BENCHMARK,
        current_line="1.1.x",
        allowed_capabilities=frozenset({"research", "backtest", "metrics"}),
        financial_authority=False,
        real_capital_allowed=False,
        rationale="Useful high-performance independent research/backtest benchmark; never risk/execution authority.",
    ),
    "nautilus": ToolPolicy(
        name="NautilusTrader",
        role=BenchmarkRole.RUNTIME_CANDIDATE,
        current_line="2.0.0rc5",
        allowed_capabilities=frozenset({"event_replay", "backtest", "accounting_benchmark"}),
        financial_authority=False,
        real_capital_allowed=False,
        rationale="Release-candidate runtime is benchmark-only until stable and full parity gates pass.",
    ),
    "lean": ToolPolicy(
        name="LEAN",
        role=BenchmarkRole.INDEPENDENT_REFERENCE,
        current_line="external",
        allowed_capabilities=frozenset({"backtest", "simple_strategy_parity"}),
        financial_authority=False,
        real_capital_allowed=False,
        rationale="Independent implementation used for simple-strategy parity, not canonical execution.",
    ),
    "skfolio": ToolPolicy(
        name="skfolio",
        role=BenchmarkRole.OPTIMIZER_BENCHMARK,
        current_line="1.4.x",
        allowed_capabilities=frozenset({"portfolio_optimization", "risk_model_benchmark"}),
        financial_authority=False,
        real_capital_allowed=False,
        rationale="Portfolio optimizer benchmark remains subordinate to deterministic portfolio/risk limits.",
    ),
    "qlib": ToolPolicy(
        name="Qlib",
        role=BenchmarkRole.RESEARCH_BENCHMARK,
        current_line="0.9.x",
        allowed_capabilities=frozenset({"ml_research", "factor_benchmark"}),
        financial_authority=False,
        real_capital_allowed=False,
        rationale="External ML/factor benchmark; model promotion still requires project-owned validation gates.",
    ),
}


def assert_tool_capability(tool: str, capability: str) -> ToolPolicy:
    try:
        policy = TOOL_POLICY[tool.strip().lower()]
    except KeyError as exc:
        raise KeyError(f"unregistered benchmark tool: {tool}") from exc
    if capability not in policy.allowed_capabilities:
        raise PermissionError(f"{policy.name} is not authorized for capability: {capability}")
    return policy


def assert_external_tool_has_no_financial_authority(tool: str) -> None:
    policy = TOOL_POLICY[tool.strip().lower()]
    if tool.strip().lower() != "internal" and policy.financial_authority:
        raise RuntimeError("external benchmark cannot hold canonical financial authority")


__all__ = [
    "BenchmarkRole",
    "TOOL_POLICY",
    "ToolPolicy",
    "assert_external_tool_has_no_financial_authority",
    "assert_tool_capability",
]

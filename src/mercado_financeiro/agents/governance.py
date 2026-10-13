from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from types import ModuleType


class ToolDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


_TOOL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


def _canonical_tool_name(value: object) -> str:
    name = str(value).strip().lower()
    if not _TOOL_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid tool name: {value!r}")
    return name


@dataclass(frozen=True)
class ResearchToolPolicy:
    """Fail-closed tool policy for LLM-backed financial research agents.

    Names are canonicalized at construction so case tricks cannot bypass
    execution/risk deny rules. Invalid or forbidden authorization configuration
    is rejected immediately instead of being tolerated until runtime.
    """

    allowed_tools: frozenset[str] = frozenset()
    approval_required_tools: frozenset[str] = frozenset()
    forbidden_prefixes: tuple[str, ...] = (
        "broker.",
        "execution.",
        "risk.override",
        "risk.limit.",
        "kill_switch.",
        "live.",
    )

    def __post_init__(self) -> None:
        allowed = frozenset(_canonical_tool_name(name) for name in self.allowed_tools)
        approval = frozenset(
            _canonical_tool_name(name) for name in self.approval_required_tools
        )
        prefixes = tuple(_canonical_tool_name(prefix) for prefix in self.forbidden_prefixes)
        overlap = allowed.intersection(approval)
        if overlap:
            raise ValueError(
                "tools cannot be both allowed and approval-required: "
                + ",".join(sorted(overlap))
            )
        forbidden_config = sorted(
            name
            for name in allowed | approval
            if any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in prefixes)
        )
        if forbidden_config:
            raise ValueError(
                "research tool policy cannot authorize forbidden tools: "
                + ",".join(forbidden_config)
            )
        object.__setattr__(self, "allowed_tools", allowed)
        object.__setattr__(self, "approval_required_tools", approval)
        object.__setattr__(self, "forbidden_prefixes", prefixes)

    def decide(self, tool_name: str) -> ToolDecision:
        try:
            name = _canonical_tool_name(tool_name)
        except ValueError:
            return ToolDecision.DENY
        if any(
            name == prefix.rstrip(".") or name.startswith(prefix)
            for prefix in self.forbidden_prefixes
        ):
            return ToolDecision.DENY
        if name in self.approval_required_tools:
            return ToolDecision.REQUIRE_APPROVAL
        if name in self.allowed_tools:
            return ToolDecision.ALLOW
        return ToolDecision.DENY


@dataclass(frozen=True)
class ResearchArtifact:
    """Hypothesis-only output from an LLM research layer."""

    artifact_id: str
    hypothesis: str
    evidence_refs: tuple[str, ...]
    uncertainty: str
    generated_by: str

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id is required")
        if not self.hypothesis.strip():
            raise ValueError("hypothesis is required")
        if not self.evidence_refs:
            raise ValueError("research artifact requires evidence_refs")
        if any(not str(ref).strip() for ref in self.evidence_refs):
            raise ValueError("evidence_refs cannot contain blank values")
        if not self.uncertainty.strip():
            raise ValueError("uncertainty is required")
        if not self.generated_by.strip():
            raise ValueError("generated_by is required")


class SpendLimitExceeded(RuntimeError):
    pass


@dataclass
class AgentSpendLedger:
    """Deterministic spend/token gate independent of an agent framework."""

    max_cost_usd: Decimal
    max_input_tokens: int
    max_output_tokens: int
    cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")
        if self.max_input_tokens < 0 or self.max_output_tokens < 0:
            raise ValueError("token limits cannot be negative")

    def reserve(
        self,
        *,
        cost_usd: Decimal | str | float = Decimal("0"),
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        cost = Decimal(str(cost_usd))
        if cost < 0 or input_tokens < 0 or output_tokens < 0:
            raise ValueError("spend increments cannot be negative")

        next_cost = self.cost_usd + cost
        next_input = self.input_tokens + int(input_tokens)
        next_output = self.output_tokens + int(output_tokens)

        violations: list[str] = []
        if next_cost > self.max_cost_usd:
            violations.append("cost_usd")
        if next_input > self.max_input_tokens:
            violations.append("input_tokens")
        if next_output > self.max_output_tokens:
            violations.append("output_tokens")
        if violations:
            raise SpendLimitExceeded(
                "agent spend limit exceeded: " + ",".join(violations)
            )

        self.cost_usd = next_cost
        self.input_tokens = next_input
        self.output_tokens = next_output


@dataclass(frozen=True)
class PydanticHarnessProfile:
    """Capability contract used to isolate the project from Harness 0.x APIs."""

    required_capabilities: tuple[str, ...] = (
        "Planning",
        "SubAgents",
        "Memory",
        "SpendLimits",
        "TrajectoryJudge",
        "DynamicWorkflow",
    )
    require_tool_approval: bool = True
    hypothesis_only: bool = True


def missing_harness_capabilities(
    module: ModuleType | object,
    profile: PydanticHarnessProfile | None = None,
) -> tuple[str, ...]:
    active = profile or PydanticHarnessProfile()
    return tuple(
        capability
        for capability in active.required_capabilities
        if not hasattr(module, capability)
    )

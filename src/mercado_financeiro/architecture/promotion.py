from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import DeploymentStage, REQUIRED_LIVE_GATES, evaluate_live_promotion


_PROMOTION_ORDER = (
    DeploymentStage.RESEARCH,
    DeploymentStage.BACKTEST,
    DeploymentStage.WALK_FORWARD,
    DeploymentStage.PAPER,
    DeploymentStage.SHADOW,
    DeploymentStage.LIVE,
)

_REQUIRED_BY_TARGET: dict[DeploymentStage, tuple[str, ...]] = {
    DeploymentStage.BACKTEST: ("historical_data_gate", "source_integrity"),
    DeploymentStage.WALK_FORWARD: ("backtest",),
    DeploymentStage.PAPER: ("walk_forward", "security_test", "risk_validation"),
    DeploymentStage.SHADOW: ("paper", "reconciliation"),
    DeploymentStage.LIVE: REQUIRED_LIVE_GATES,
}


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    current: DeploymentStage
    target: DeploymentStage
    missing: tuple[str, ...]
    failed: tuple[str, ...]
    reason: str | None = None


def evaluate_stage_promotion(
    current: DeploymentStage,
    target: DeploymentStage,
    evidence: Mapping[str, bool | None],
) -> PromotionDecision:
    """Allow only adjacent forward deployment promotions and fail closed on evidence."""

    current_index = _PROMOTION_ORDER.index(current)
    target_index = _PROMOTION_ORDER.index(target)
    if target_index != current_index + 1:
        return PromotionDecision(
            approved=False,
            current=current,
            target=target,
            missing=(),
            failed=(),
            reason="promotion_must_be_adjacent_and_forward",
        )

    if target is DeploymentStage.LIVE:
        gate = evaluate_live_promotion(evidence)
        return PromotionDecision(
            approved=gate.approved,
            current=current,
            target=target,
            missing=gate.missing,
            failed=gate.failed,
        )

    required = _REQUIRED_BY_TARGET.get(target, ())
    missing = tuple(name for name in required if name not in evidence or evidence[name] is None)
    failed = tuple(name for name in required if evidence.get(name) is False)
    return PromotionDecision(
        approved=not missing and not failed,
        current=current,
        target=target,
        missing=missing,
        failed=failed,
    )


def assert_stage_promotion(
    current: DeploymentStage,
    target: DeploymentStage,
    evidence: Mapping[str, bool | None],
) -> PromotionDecision:
    result = evaluate_stage_promotion(current, target, evidence)
    if not result.approved:
        parts = [result.reason] if result.reason else []
        if result.missing:
            parts.append("missing=" + ",".join(result.missing))
        if result.failed:
            parts.append("failed=" + ",".join(result.failed))
        raise RuntimeError("deployment promotion rejected: " + "; ".join(parts))
    return result

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class IdentityGatePolicy:
    min_mapped_volume_ratio: float = 0.98
    min_mapped_row_ratio: float = 0.95
    max_ambiguous_volume_ratio: float = 0.0
    max_single_unresolved_volume_ratio: float = 0.005

    def __post_init__(self) -> None:
        for name, value in (
            ("min_mapped_volume_ratio", self.min_mapped_volume_ratio),
            ("min_mapped_row_ratio", self.min_mapped_row_ratio),
            ("max_ambiguous_volume_ratio", self.max_ambiguous_volume_ratio),
            ("max_single_unresolved_volume_ratio", self.max_single_unresolved_volume_ratio),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class IdentityGateResult:
    passed: bool
    rows: int
    mapped_rows: int
    mapped_row_ratio: float
    total_volume: float
    mapped_volume: float
    mapped_volume_ratio: float
    ambiguous_volume_ratio: float
    largest_unresolved_volume_ratio: float
    unresolved_securities: int
    reasons: tuple[str, ...]


def evaluate_identity_gate(
    universe: pd.DataFrame,
    policy: IdentityGatePolicy | None = None,
) -> IdentityGateResult:
    policy = policy or IdentityGatePolicy()
    required = {"security_id", "identity_mapping_status", "financial_volume"}
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"missing identity gate columns: {sorted(missing)}")

    frame = universe.copy()
    frame["financial_volume"] = pd.to_numeric(frame["financial_volume"], errors="coerce")
    if frame["financial_volume"].isna().any() or (frame["financial_volume"] < 0).any():
        raise ValueError("identity gate requires finite non-negative financial_volume")

    rows = len(frame)
    resolved = frame["identity_mapping_status"].eq("resolved")
    mapped_rows = int(resolved.sum())
    mapped_row_ratio = mapped_rows / rows if rows else 0.0
    total_volume = float(frame["financial_volume"].sum())
    mapped_volume = float(frame.loc[resolved, "financial_volume"].sum())
    mapped_volume_ratio = mapped_volume / total_volume if total_volume > 0 else 0.0

    ambiguous = frame["identity_mapping_status"].astype(str).str.startswith("ambiguous")
    ambiguous_volume = float(frame.loc[ambiguous, "financial_volume"].sum())
    ambiguous_volume_ratio = ambiguous_volume / total_volume if total_volume > 0 else 0.0

    unresolved = frame.loc[~resolved].copy()
    unresolved_securities = unresolved["security_id"].nunique()
    if total_volume > 0 and not unresolved.empty:
        by_security = unresolved.groupby("security_id")["financial_volume"].sum()
        largest_unresolved_volume_ratio = float(by_security.max() / total_volume)
    else:
        largest_unresolved_volume_ratio = 0.0

    reasons: list[str] = []
    if rows == 0 or total_volume <= 0:
        reasons.append("empty_or_zero_volume_universe")
    if mapped_volume_ratio < policy.min_mapped_volume_ratio:
        reasons.append(
            f"mapped_volume_ratio={mapped_volume_ratio:.6f}<minimum={policy.min_mapped_volume_ratio:.6f}"
        )
    if mapped_row_ratio < policy.min_mapped_row_ratio:
        reasons.append(
            f"mapped_row_ratio={mapped_row_ratio:.6f}<minimum={policy.min_mapped_row_ratio:.6f}"
        )
    if ambiguous_volume_ratio > policy.max_ambiguous_volume_ratio:
        reasons.append(
            f"ambiguous_volume_ratio={ambiguous_volume_ratio:.6f}>maximum={policy.max_ambiguous_volume_ratio:.6f}"
        )
    if largest_unresolved_volume_ratio > policy.max_single_unresolved_volume_ratio:
        reasons.append(
            "largest_unresolved_volume_ratio="
            f"{largest_unresolved_volume_ratio:.6f}>maximum={policy.max_single_unresolved_volume_ratio:.6f}"
        )

    return IdentityGateResult(
        passed=not reasons,
        rows=rows,
        mapped_rows=mapped_rows,
        mapped_row_ratio=mapped_row_ratio,
        total_volume=total_volume,
        mapped_volume=mapped_volume,
        mapped_volume_ratio=mapped_volume_ratio,
        ambiguous_volume_ratio=ambiguous_volume_ratio,
        largest_unresolved_volume_ratio=largest_unresolved_volume_ratio,
        unresolved_securities=unresolved_securities,
        reasons=tuple(reasons),
    )


def assert_identity_gate(
    universe: pd.DataFrame,
    policy: IdentityGatePolicy | None = None,
) -> IdentityGateResult:
    result = evaluate_identity_gate(universe, policy)
    if not result.passed:
        raise RuntimeError("historical identity gate failed: " + "; ".join(result.reasons))
    return result

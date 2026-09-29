from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd


FACTOR_COMPONENTS: Mapping[str, tuple[tuple[str, bool], ...]] = {
    "value": (("earnings_yield", True), ("book_to_market", True), ("free_cash_flow_yield", True)),
    "quality": (("roe", True), ("gross_profitability", True), ("cash_return_on_assets", True)),
    "momentum": (("momentum_63", True), ("momentum_252", True)),
    "low_risk": (("volatility_63", False), ("beta_252", False), ("max_drawdown_abs_252", False)),
    "liquidity": (("adv_21", True), ("turnover_21", True)),
}


@dataclass(frozen=True)
class FactorScoreAudit:
    rows: int
    dates: int
    securities: int
    factors_computed: tuple[str, ...]
    source_lookahead_rows: int


def _percentile_rank(values: pd.Series, *, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() == 0:
        return pd.Series(float("nan"), index=values.index, dtype=float)
    return numeric.rank(pct=True, method="average", ascending=higher_is_better)


def _factor_for_group(
    group: pd.DataFrame,
    components: Sequence[tuple[str, bool]],
) -> pd.Series:
    available = [(name, direction) for name, direction in components if name in group.columns]
    if not available:
        return pd.Series(float("nan"), index=group.index, dtype=float)
    ranks = [
        _percentile_rank(group[name], higher_is_better=direction)
        for name, direction in available
    ]
    return pd.concat(ranks, axis=1).mean(axis=1, skipna=True)


def build_cross_sectional_factor_scores(
    frame: pd.DataFrame,
    *,
    security_column: str = "security_id",
    date_column: str = "feature_date",
) -> tuple[pd.DataFrame, FactorScoreAudit]:
    """Create transparent PIT cross-sectional factor scores.

    Scores are percentile ranks computed only among securities sharing the same
    feature date. This is a research baseline, not an alpha assertion.
    """

    required = {security_column, date_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing factor identity columns: {sorted(missing)}")
    out = frame.copy().reset_index(drop=True)
    out[security_column] = out[security_column].astype(str).str.strip().str.upper()
    out[date_column] = pd.to_datetime(out[date_column], errors="coerce", utc=True)
    if out[security_column].eq("").any() or out[date_column].isna().any():
        raise ValueError("invalid factor security/date")
    if out.duplicated([security_column, date_column]).any():
        raise ValueError("duplicate security/date rows in factor input")

    lookahead_rows = 0
    if "source_max_date" in out.columns:
        source = pd.to_datetime(out["source_max_date"], errors="coerce", utc=True)
        bad = source.notna() & (source >= out[date_column])
        lookahead_rows = int(bad.sum())
        if lookahead_rows:
            raise RuntimeError("factor input contains look-ahead information")

    computed: list[str] = []
    for factor, components in FACTOR_COMPONENTS.items():
        if not any(name in out.columns for name, _ in components):
            continue
        scores = pd.Series(float("nan"), index=out.index, dtype=float)
        for _, index in out.groupby(date_column, sort=False).groups.items():
            group = out.loc[index]
            scores.loc[index] = _factor_for_group(group, components)
        out[f"{factor}_score"] = scores
        computed.append(factor)

    if not computed:
        raise ValueError("factor input does not contain any canonical factor component")

    score_columns = [f"{factor}_score" for factor in computed]
    out["multifactor_score"] = out[score_columns].mean(axis=1, skipna=True)
    return out, FactorScoreAudit(
        rows=len(out),
        dates=out[date_column].nunique(),
        securities=out[security_column].nunique(),
        factors_computed=tuple(computed),
        source_lookahead_rows=lookahead_rows,
    )


__all__ = ["FACTOR_COMPONENTS", "FactorScoreAudit", "build_cross_sectional_factor_scores"]

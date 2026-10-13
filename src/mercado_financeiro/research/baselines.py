from __future__ import annotations

import pandas as pd


def _normalize_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or (numeric < 0).any():
        raise ValueError("weights input must be finite and non-negative")
    total = float(numeric.sum())
    if total <= 0:
        raise ValueError("weights input must have positive sum")
    return numeric.astype(float) / total


def equal_weight(securities: pd.Series | list[str]) -> pd.Series:
    index = pd.Index(list(securities), dtype="object")
    if index.empty:
        raise ValueError("at least one security is required")
    if index.has_duplicates:
        raise ValueError("securities must be unique")
    return pd.Series(1.0 / len(index), index=index, name="weight")


def market_cap_weight(market_caps: pd.Series) -> pd.Series:
    if market_caps.index.has_duplicates:
        raise ValueError("market cap index must contain unique securities")
    out = _normalize_positive(market_caps)
    out.name = "weight"
    return out


def inverse_volatility_weight(volatility: pd.Series) -> pd.Series:
    if volatility.index.has_duplicates:
        raise ValueError("volatility index must contain unique securities")
    values = pd.to_numeric(volatility, errors="coerce")
    if values.isna().any() or (values <= 0).any():
        raise ValueError("volatility must be finite and strictly positive")
    out = _normalize_positive(1.0 / values)
    out.name = "weight"
    return out


def top_quantile_equal_weight(
    scores: pd.Series,
    *,
    quantile: float = 0.20,
    minimum_names: int = 1,
) -> pd.Series:
    """Transparent long-only factor baseline with deterministic tie ordering."""

    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    if minimum_names <= 0:
        raise ValueError("minimum_names must be positive")
    if scores.index.has_duplicates:
        raise ValueError("score index must contain unique securities")
    values = pd.to_numeric(scores, errors="coerce").dropna()
    if values.empty:
        raise ValueError("no finite scores")
    count = max(minimum_names, int(len(values) * quantile))
    count = min(count, len(values))
    ranked = pd.DataFrame({"score": values, "security": values.index.astype(str)})
    ranked = ranked.sort_values(["score", "security"], ascending=[False, True], kind="stable")
    selected = ranked.index[:count]
    result = pd.Series(0.0, index=scores.index, name="weight")
    result.loc[selected] = 1.0 / count
    return result


def assert_long_only_weights(weights: pd.Series, *, tolerance: float = 1e-10) -> None:
    values = pd.to_numeric(weights, errors="coerce")
    if values.isna().any():
        raise ValueError("weights contain non-numeric values")
    if (values < -tolerance).any():
        raise ValueError("long-only weights cannot be negative")
    if abs(float(values.sum()) - 1.0) > tolerance:
        raise ValueError("portfolio weights must sum to one")

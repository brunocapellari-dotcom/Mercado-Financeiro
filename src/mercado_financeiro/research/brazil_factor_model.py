from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BrazilFactorModelResult:
    observations: int
    factors: tuple[str, ...]
    alpha_daily: float
    betas: dict[str, float]
    r_squared: float


def fit_brazil_factor_model(
    asset_excess_returns: pd.Series,
    factor_returns: pd.DataFrame,
    *,
    factor_columns: Sequence[str],
) -> BrazilFactorModelResult:
    """Fit an auditable OLS exposure model against Brazilian benchmark factors.

    Intended primarily for NEFIN reconciliation/validation. It does not promote a
    factor to a trading feature and does not bypass PIT constraints.
    """

    columns = tuple(str(name) for name in factor_columns)
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("factor_columns must be a non-empty unique sequence")
    missing = set(columns) - set(factor_returns.columns)
    if missing:
        raise ValueError(f"missing factor columns: {sorted(missing)}")

    joined = pd.concat(
        [
            pd.to_numeric(asset_excess_returns, errors="coerce").rename("asset"),
            factor_returns.loc[:, columns].apply(pd.to_numeric, errors="coerce"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(joined) <= len(columns) + 1:
        raise ValueError("insufficient observations for factor regression")

    y = joined["asset"].to_numpy(dtype=float)
    x_factors = joined.loc[:, columns].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(joined), dtype=float), x_factors])
    if np.linalg.matrix_rank(x) < x.shape[1]:
        raise ValueError("factor design matrix is rank deficient")

    coefficients, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ coefficients
    residual = y - fitted
    total = float(np.sum((y - y.mean()) ** 2))
    residual_ss = float(np.sum(residual**2))
    r_squared = 0.0 if total <= 0 else 1.0 - residual_ss / total

    return BrazilFactorModelResult(
        observations=len(joined),
        factors=columns,
        alpha_daily=float(coefficients[0]),
        betas={name: float(value) for name, value in zip(columns, coefficients[1:], strict=True)},
        r_squared=float(r_squared),
    )


__all__ = ["BrazilFactorModelResult", "fit_brazil_factor_model"]

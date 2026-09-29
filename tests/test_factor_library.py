import pandas as pd
import pytest

from mercado_financeiro.research.factors import build_cross_sectional_factor_scores
from mercado_financeiro.research.catalog import DEFAULT_RESEARCH_CATALOG


def test_factor_library_builds_five_transparent_cross_sectional_scores():
    frame = pd.DataFrame(
        {
            "security_id": ["A", "B", "C"],
            "feature_date": ["2026-09-29"] * 3,
            "source_max_date": ["2026-09-28"] * 3,
            "earnings_yield": [0.10, 0.05, 0.02],
            "book_to_market": [1.2, 0.8, 0.5],
            "roe": [0.25, 0.15, 0.05],
            "gross_profitability": [0.30, 0.20, 0.10],
            "momentum_63": [0.20, 0.10, -0.10],
            "momentum_252": [0.30, 0.05, -0.20],
            "volatility_63": [0.10, 0.20, 0.30],
            "beta_252": [0.8, 1.0, 1.4],
            "adv_21": [5_000_000, 2_000_000, 500_000],
            "turnover_21": [0.04, 0.02, 0.01],
        }
    )
    out, audit = build_cross_sectional_factor_scores(frame)
    assert set(audit.factors_computed) == {"value", "quality", "momentum", "low_risk", "liquidity"}
    assert out.loc[out["security_id"].eq("A"), "multifactor_score"].iloc[0] > out.loc[
        out["security_id"].eq("C"), "multifactor_score"
    ].iloc[0]
    assert set(DEFAULT_RESEARCH_CATALOG) == {"value", "momentum", "quality", "low_risk", "liquidity"}


def test_factor_library_fails_closed_on_same_day_source():
    frame = pd.DataFrame(
        {
            "security_id": ["A"],
            "feature_date": ["2026-09-29"],
            "source_max_date": ["2026-09-29"],
            "momentum_63": [0.1],
        }
    )
    with pytest.raises(RuntimeError, match="look-ahead"):
        build_cross_sectional_factor_scores(frame)

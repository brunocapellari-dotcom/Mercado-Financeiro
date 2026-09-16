from __future__ import annotations

import math

import pandas as pd

from mercado_financeiro.research import independent_spa_mcs_validation


def test_independent_spa_mcs_validation_returns_bounded_reproducible_statistics():
    index = pd.date_range("2020-01-01", periods=120, freq="B")
    returns = pd.DataFrame(
        {
            "alpha": [0.0010 + 0.0005 * math.sin(i / 3) for i in range(120)],
            "beta": [-0.0002 + 0.0006 * math.cos(i / 5) for i in range(120)],
            "flat": [0.0001 * math.sin(i / 7) for i in range(120)],
        },
        index=index,
    )
    result = independent_spa_mcs_validation(
        returns,
        block_size=5,
        bootstrap_reps=50,
        seed=1234,
    )
    assert result.observations == 120
    assert result.strategies == 3
    assert 0.0 <= result.spa_lower_pvalue <= 1.0
    assert 0.0 <= result.spa_consistent_pvalue <= 1.0
    assert 0.0 <= result.spa_upper_pvalue <= 1.0
    assert set(result.spa_better_models).issubset(set(returns.columns))
    assert set(result.mcs_included_models).issubset(set(returns.columns))
    assert not result.mcs_pvalues.empty


def test_independent_validation_rejects_too_short_or_single_strategy_samples():
    one = pd.DataFrame({"only": [0.0] * 30})
    try:
        independent_spa_mcs_validation(one, bootstrap_reps=10)
    except ValueError as exc:
        assert "at least two strategies" in str(exc)
    else:
        raise AssertionError("single-strategy validation should fail")

    short = pd.DataFrame({"a": [0.0] * 10, "b": [0.1] * 10})
    try:
        independent_spa_mcs_validation(short, bootstrap_reps=10)
    except ValueError as exc:
        assert "at least 20 observations" in str(exc)
    else:
        raise AssertionError("short validation sample should fail")

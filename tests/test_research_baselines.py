import pandas as pd
import pytest

from mercado_financeiro.research import (
    assert_long_only_weights,
    equal_weight,
    inverse_volatility_weight,
    market_cap_weight,
    top_quantile_equal_weight,
)


def test_baselines_are_normalized_and_transparent():
    equal = equal_weight(["PETR4", "VALE3", "ITUB4"])
    assert_long_only_weights(equal)
    assert equal.sum() == pytest.approx(1.0)

    cap = market_cap_weight(pd.Series({"PETR4": 50.0, "VALE3": 30.0, "ITUB4": 20.0}))
    assert cap["PETR4"] == pytest.approx(0.5)
    assert_long_only_weights(cap)

    inv = inverse_volatility_weight(pd.Series({"A": 0.10, "B": 0.20}))
    assert inv["A"] == pytest.approx(2.0 / 3.0)
    assert_long_only_weights(inv)


def test_factor_baseline_is_deterministic_and_long_only():
    scores = pd.Series({"BBB": 3.0, "AAA": 3.0, "CCC": 1.0, "DDD": 0.0})
    weights = top_quantile_equal_weight(scores, quantile=0.5)
    assert weights["AAA"] == pytest.approx(0.5)
    assert weights["BBB"] == pytest.approx(0.5)
    assert weights["CCC"] == 0
    assert_long_only_weights(weights)

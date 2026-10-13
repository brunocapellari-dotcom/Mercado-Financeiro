import pandas as pd

from mercado_financeiro.research.stress import block_bootstrap_stress, historical_window_stress


def test_block_bootstrap_stress_is_reproducible():
    values = pd.Series([0.01, -0.005, 0.002, -0.003, 0.004] * 20)
    a = block_bootstrap_stress(values, paths=50, horizon=30, block_size=5, seed=7)
    b = block_bootstrap_stress(values, paths=50, horizon=30, block_size=5, seed=7)
    assert a == b
    assert a.paths == 50
    assert a.worst_max_drawdown <= 0


def test_historical_window_stress_uses_only_requested_window():
    index = pd.date_range("2020-03-01", periods=10, freq="D")
    values = pd.Series([-0.01, -0.02, 0.01, -0.03, 0.02, 0.01, 0.0, 0.01, -0.01, 0.02], index=index)
    result = historical_window_stress(values, start="2020-03-02", end="2020-03-05")
    assert result.observations == 4
    assert result.max_drawdown <= 0

from __future__ import annotations

import pandas as pd
import pytest

from mercado_financeiro.research import TournamentPrerequisites, run_oos_tournament


def _ready() -> TournamentPrerequisites:
    return TournamentPrerequisites(
        historical_identity=True,
        market_cap_pit=True,
        total_return_reconciled=True,
        fundamentals_pit=True,
        feature_mart_pit=True,
        source_integrity=True,
        transaction_cost_model=True,
    )


def test_oos_tournament_applies_common_costs_multiple_testing_and_stress():
    index = pd.date_range("2024-01-01", periods=120, freq="B")
    base = pd.Series(
        [0.004, -0.001, 0.003, 0.001, -0.0005, 0.002] * 20,
        index=index,
    )
    gross = pd.DataFrame(
        {
            "quality": base,
            "momentum": base * 0.55,
            "weak": -base * 0.15,
        },
        index=index,
    )
    turnover = pd.DataFrame(
        {
            "quality": [0.08] * len(index),
            "momentum": [0.25] * len(index),
            "weak": [0.10] * len(index),
        },
        index=index,
    )

    result = run_oos_tournament(
        gross,
        turnover,
        prerequisites=_ready(),
        base_cost_bps=10,
        stress_cost_bps=(10, 25, 50),
        pbo_blocks=6,
        bootstrap_samples=100,
        bootstrap_block_size=5,
        seed=42,
    )
    assert result.winner == "quality"
    assert result.observations == 120
    assert result.number_of_trials == 3
    assert 0.0 <= result.pbo <= 1.0
    assert 0.0 <= result.reality_check_p_value <= 1.0
    assert {item.strategy for item in result.strategies} == {"quality", "momentum", "weak"}
    for item in result.strategies:
        assert 0.0 <= item.probabilistic_sharpe <= 1.0
        assert 0.0 <= item.deflated_sharpe <= 1.0
        assert item.worst_stress_cost_bps in {10.0, 25.0, 50.0}


def test_oos_tournament_is_blocked_until_every_prerequisite_is_green():
    returns = pd.DataFrame({"a": [0.01, -0.01] * 20, "b": [0.005, -0.004] * 20})
    turnover = pd.DataFrame({"a": [0.1] * 40, "b": [0.1] * 40})
    with pytest.raises(RuntimeError, match="Tournament blocked"):
        run_oos_tournament(
            returns,
            turnover,
            prerequisites=TournamentPrerequisites(),
            base_cost_bps=5,
            pbo_blocks=4,
            bootstrap_samples=20,
        )


def test_oos_tournament_rejects_misaligned_turnover_and_negative_costs():
    returns = pd.DataFrame({"a": [0.01, -0.01] * 20, "b": [0.005, -0.004] * 20})
    turnover = pd.DataFrame({"b": [0.1] * 40, "a": [0.1] * 40})
    with pytest.raises(ValueError, match="columns"):
        run_oos_tournament(
            returns,
            turnover,
            prerequisites=_ready(),
            base_cost_bps=5,
            pbo_blocks=4,
            bootstrap_samples=20,
        )
    with pytest.raises(ValueError, match="base_cost_bps"):
        run_oos_tournament(
            returns,
            returns.abs(),
            prerequisites=_ready(),
            base_cost_bps=-1,
            pbo_blocks=4,
            bootstrap_samples=20,
        )

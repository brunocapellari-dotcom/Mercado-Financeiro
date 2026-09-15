import pandas as pd
import pytest

from mercado_financeiro.research import (
    TournamentPrerequisites,
    apply_transaction_costs,
    assert_tournament_ready,
    build_price_features_pit,
    deflated_sharpe_ratio,
    evaluate_tournament_readiness,
    performance_metrics,
    point_in_time_asof_join,
    probability_of_backtest_overfitting,
    walk_forward_splits,
    whites_reality_check,
)


def test_tournament_is_blocked_until_every_data_and_cost_gate_is_green():
    result = evaluate_tournament_readiness(TournamentPrerequisites())
    assert not result.approved
    assert "historical_identity" in result.missing
    assert "transaction_cost_model" in result.missing
    with pytest.raises(RuntimeError, match="Tournament blocked"):
        assert_tournament_ready(TournamentPrerequisites())

    ready = TournamentPrerequisites(
        historical_identity=True,
        market_cap_pit=True,
        total_return_reconciled=True,
        fundamentals_pit=True,
        feature_mart_pit=True,
        source_integrity=True,
        transaction_cost_model=True,
    )
    assert assert_tournament_ready(ready).approved


def test_walk_forward_is_chronological_with_embargo():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    splits = walk_forward_splits(
        dates,
        train_periods=10,
        validation_periods=5,
        test_periods=5,
        embargo_periods=2,
    )
    assert splits
    first = splits[0]
    assert first.train_end < first.validation_start < first.validation_end < first.test_start
    assert (first.validation_start - first.train_end).days == 3
    assert (first.test_start - first.validation_end).days == 3


def test_price_features_never_use_current_day_market_observable():
    dates = pd.date_range("2026-01-01", periods=70, freq="D")
    frame = pd.DataFrame(
        {
            "security_id": ["TEST3"] * len(dates),
            "price_date": dates,
            "close_price": [100.0 + i for i in range(len(dates))],
            "financial_volume": [1_000_000.0 + i for i in range(len(dates))],
        }
    )
    mart, audit = build_price_features_pit(frame)
    assert audit.leakage_rows == 0
    row = mart.loc[mart["feature_date"] == dates[30]].iloc[0]
    assert row["source_max_date"] == dates[29]

    shocked = frame.copy()
    shocked.loc[shocked["price_date"] == dates[30], "close_price"] = 1_000_000.0
    mart2, _ = build_price_features_pit(shocked)
    row2 = mart2.loc[mart2["feature_date"] == dates[30]].iloc[0]
    assert row2["momentum_21"] == pytest.approx(row["momentum_21"])
    assert row2["volatility_21"] == pytest.approx(row["volatility_21"])


def test_fundamentals_join_uses_available_from_not_reference_date():
    observations = pd.DataFrame(
        {
            "issuer_id": ["A", "A"],
            "feature_date": pd.to_datetime(["2026-03-01", "2026-05-01"]),
        }
    )
    fundamentals = pd.DataFrame(
        {
            "issuer_id": ["A"],
            "reference_date": pd.to_datetime(["2025-12-31"]),
            "available_from": pd.to_datetime(["2026-04-01"]),
            "book_value": [123.0],
        }
    )
    joined = point_in_time_asof_join(observations, fundamentals)
    assert pd.isna(joined.loc[0, "book_value"])
    assert joined.loc[1, "book_value"] == 123.0


def test_costs_and_metrics_are_net_of_turnover():
    gross = pd.Series([0.01, -0.005, 0.002, 0.004])
    turnover = pd.Series([1.0, 0.5, 0.25, 0.1])
    net = apply_transaction_costs(gross, turnover, one_way_cost_bps=10)
    assert net.iloc[0] == pytest.approx(0.009)
    metrics = performance_metrics(net)
    assert metrics.observations == 4
    assert metrics.max_drawdown <= 0


def test_multiple_testing_statistics_are_bounded():
    returns = pd.Series([0.01, -0.004, 0.007, -0.002, 0.005, 0.003, -0.001, 0.004] * 10)
    dsr = deflated_sharpe_ratio(returns, number_of_trials=20)
    assert 0.0 <= dsr <= 1.0

    strategies = pd.DataFrame(
        {
            "a": returns.reset_index(drop=True),
            "b": (returns * 0.2 - 0.0005).reset_index(drop=True),
            "c": (-returns * 0.1).reset_index(drop=True),
        }
    )
    pbo = probability_of_backtest_overfitting(strategies, blocks=4)
    reality = whites_reality_check(strategies, bootstrap_samples=100, block_size=4, seed=42)
    assert 0.0 <= pbo <= 1.0
    assert 0.0 <= reality <= 1.0

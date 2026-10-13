from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .tournament import (
    PerformanceMetrics,
    TournamentPrerequisites,
    apply_transaction_costs,
    assert_tournament_ready,
    deflated_sharpe_ratio,
    performance_metrics,
    probability_of_backtest_overfitting,
    probabilistic_sharpe_ratio,
    whites_reality_check,
)


@dataclass(frozen=True)
class StrategyTournamentResult:
    strategy: str
    metrics: PerformanceMetrics
    probabilistic_sharpe: float
    deflated_sharpe: float
    worst_stress_sharpe: float
    worst_stress_cost_bps: float


@dataclass(frozen=True)
class TournamentResult:
    winner: str
    observations: int
    number_of_trials: int
    base_cost_bps: float
    pbo: float
    reality_check_p_value: float
    strategies: tuple[StrategyTournamentResult, ...]


def run_oos_tournament(
    gross_oos_returns: pd.DataFrame,
    turnover: pd.DataFrame,
    *,
    prerequisites: TournamentPrerequisites,
    base_cost_bps: float,
    stress_cost_bps: Iterable[float] = (0.0, 5.0, 10.0, 20.0, 50.0),
    pbo_blocks: int = 10,
    bootstrap_samples: int = 1000,
    bootstrap_block_size: int = 5,
    seed: int = 0,
) -> TournamentResult:
    """Run the common OOS strategy Tournament under one auditable policy.

    Inputs must already be out-of-sample strategy return streams produced by the
    purged walk-forward research path.  The function applies the same one-way cost
    convention to every candidate, calculates multiple-testing diagnostics and
    reruns every candidate under explicit transaction-cost stress.  It deliberately
    does not promote a winner to live execution; promotion remains a separate risk
    gate.
    """

    assert_tournament_ready(prerequisites)
    if base_cost_bps < 0:
        raise ValueError("base_cost_bps cannot be negative")
    if gross_oos_returns.empty:
        raise ValueError("Tournament requires non-empty OOS returns")
    if gross_oos_returns.shape[1] < 2:
        raise ValueError("Tournament requires at least two competing strategies")
    if not gross_oos_returns.index.equals(turnover.index):
        raise ValueError("turnover index must exactly match OOS return index")
    if list(gross_oos_returns.columns) != list(turnover.columns):
        raise ValueError("turnover columns must exactly match OOS strategy columns")
    if gross_oos_returns.columns.duplicated().any():
        raise ValueError("strategy names must be unique")

    gross = gross_oos_returns.apply(pd.to_numeric, errors="coerce")
    turn = turnover.apply(pd.to_numeric, errors="coerce")
    if gross.isna().any().any() or turn.isna().any().any():
        raise ValueError("Tournament returns/turnover must be finite")
    if (turn < 0).any().any():
        raise ValueError("Tournament turnover cannot be negative")
    if (gross <= -1.0).any().any():
        raise ValueError("gross returns cannot be <= -100%")

    stress = sorted({float(base_cost_bps), *(float(value) for value in stress_cost_bps)})
    if any(value < 0 for value in stress):
        raise ValueError("stress costs cannot be negative")

    net_by_cost: dict[float, pd.DataFrame] = {}
    for cost in stress:
        net = pd.DataFrame(index=gross.index)
        for strategy in gross.columns:
            net[strategy] = apply_transaction_costs(
                gross[strategy],
                turn[strategy],
                one_way_cost_bps=cost,
            )
        if (net <= -1.0).any().any():
            raise ValueError(f"cost stress {cost:g} bps produces return <= -100%")
        net_by_cost[cost] = net

    base_net = net_by_cost[float(base_cost_bps)]
    pbo = probability_of_backtest_overfitting(base_net, blocks=pbo_blocks)
    reality = whites_reality_check(
        base_net,
        bootstrap_samples=bootstrap_samples,
        block_size=bootstrap_block_size,
        seed=seed,
    )

    strategy_results: list[StrategyTournamentResult] = []
    trials = base_net.shape[1]
    for strategy in base_net.columns:
        metrics = performance_metrics(base_net[strategy])
        stress_metrics = {
            cost: performance_metrics(matrix[strategy]) for cost, matrix in net_by_cost.items()
        }
        worst_cost, worst_metrics = min(
            stress_metrics.items(), key=lambda item: (item[1].sharpe, item[0])
        )
        strategy_results.append(
            StrategyTournamentResult(
                strategy=str(strategy),
                metrics=metrics,
                probabilistic_sharpe=probabilistic_sharpe_ratio(base_net[strategy]),
                deflated_sharpe=deflated_sharpe_ratio(
                    base_net[strategy], number_of_trials=trials
                ),
                worst_stress_sharpe=worst_metrics.sharpe,
                worst_stress_cost_bps=worst_cost,
            )
        )

    # Deterministic ranking.  Statistical diagnostics are reported rather than
    # hidden in selection logic so the independent promotion gate can set policy.
    winner = max(
        strategy_results,
        key=lambda item: (
            item.metrics.sharpe,
            item.deflated_sharpe,
            item.worst_stress_sharpe,
            item.metrics.annualized_return,
            item.strategy,
        ),
    ).strategy
    return TournamentResult(
        winner=winner,
        observations=len(base_net),
        number_of_trials=trials,
        base_cost_bps=float(base_cost_bps),
        pbo=float(pbo),
        reality_check_p_value=float(reality),
        strategies=tuple(strategy_results),
    )

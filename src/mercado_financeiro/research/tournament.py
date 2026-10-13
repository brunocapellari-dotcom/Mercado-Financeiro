from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import exp, log, sqrt
from random import Random
from statistics import NormalDist

import pandas as pd


@dataclass(frozen=True)
class TournamentPrerequisites:
    historical_identity: bool = False
    market_cap_pit: bool = False
    total_return_reconciled: bool = False
    fundamentals_pit: bool = False
    feature_mart_pit: bool = False
    source_integrity: bool = False
    transaction_cost_model: bool = False


@dataclass(frozen=True)
class TournamentReadiness:
    approved: bool
    missing: tuple[str, ...]


_REQUIRED_TOURNAMENT_GATES = (
    "historical_identity",
    "market_cap_pit",
    "total_return_reconciled",
    "fundamentals_pit",
    "feature_mart_pit",
    "source_integrity",
    "transaction_cost_model",
)


def evaluate_tournament_readiness(prerequisites: TournamentPrerequisites) -> TournamentReadiness:
    missing = tuple(
        name for name in _REQUIRED_TOURNAMENT_GATES if not bool(getattr(prerequisites, name))
    )
    return TournamentReadiness(approved=not missing, missing=missing)


def assert_tournament_ready(prerequisites: TournamentPrerequisites) -> TournamentReadiness:
    result = evaluate_tournament_readiness(prerequisites)
    if not result.approved:
        raise RuntimeError("Tournament blocked: " + ", ".join(result.missing))
    return result


@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def walk_forward_splits(
    dates: pd.Series | pd.Index | list[object],
    *,
    train_periods: int,
    validation_periods: int,
    test_periods: int,
    embargo_periods: int = 0,
    step_periods: int | None = None,
) -> tuple[WalkForwardSplit, ...]:
    """Create chronological expanding-window train/validation/test splits.

    Embargo observations are left unused between train/validation and
    validation/test. ``step_periods`` defaults to the test-window length.
    """

    for name, value in (
        ("train_periods", train_periods),
        ("validation_periods", validation_periods),
        ("test_periods", test_periods),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if embargo_periods < 0:
        raise ValueError("embargo_periods cannot be negative")
    step = step_periods or test_periods
    if step <= 0:
        raise ValueError("step_periods must be positive")

    values = pd.Series(pd.to_datetime(list(dates), errors="coerce")).dropna().drop_duplicates().sort_values()
    unique = values.reset_index(drop=True)
    minimum = train_periods + validation_periods + test_periods + 2 * embargo_periods
    if len(unique) < minimum:
        return ()

    splits: list[WalkForwardSplit] = []
    train_end_index = train_periods - 1
    while True:
        validation_start_index = train_end_index + 1 + embargo_periods
        validation_end_index = validation_start_index + validation_periods - 1
        test_start_index = validation_end_index + 1 + embargo_periods
        test_end_index = test_start_index + test_periods - 1
        if test_end_index >= len(unique):
            break
        splits.append(
            WalkForwardSplit(
                train_start=unique.iloc[0],
                train_end=unique.iloc[train_end_index],
                validation_start=unique.iloc[validation_start_index],
                validation_end=unique.iloc[validation_end_index],
                test_start=unique.iloc[test_start_index],
                test_end=unique.iloc[test_end_index],
            )
        )
        train_end_index += step
    return tuple(splits)


@dataclass(frozen=True)
class PerformanceMetrics:
    observations: int
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    cdar_95: float
    hit_rate: float


def apply_transaction_costs(
    gross_returns: pd.Series,
    turnover: pd.Series,
    *,
    one_way_cost_bps: float,
) -> pd.Series:
    if one_way_cost_bps < 0:
        raise ValueError("one_way_cost_bps cannot be negative")
    gross = pd.to_numeric(gross_returns, errors="coerce")
    turn = pd.to_numeric(turnover, errors="coerce")
    if gross.isna().any() or turn.isna().any() or (turn < 0).any():
        raise ValueError("returns/turnover must be finite and turnover non-negative")
    # Turnover is defined as one-way notional traded / portfolio NAV.
    return gross - turn * (one_way_cost_bps / 10_000.0)


def performance_metrics(returns: pd.Series, *, periods_per_year: int = 252) -> PerformanceMetrics:
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if len(values) < 2:
        raise ValueError("at least two returns are required")
    if (values <= -1.0).any():
        raise ValueError("returns cannot be <= -100%")

    wealth = (1.0 + values).cumprod()
    years = len(values) / periods_per_year
    annualized_return = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0
    std = float(values.std(ddof=1))
    annualized_vol = std * sqrt(periods_per_year)
    sharpe = (float(values.mean()) / std * sqrt(periods_per_year)) if std > 0 else 0.0
    downside = values.loc[values < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) >= 2 else 0.0
    sortino = (
        float(values.mean()) / downside_std * sqrt(periods_per_year)
        if downside_std > 0
        else 0.0
    )
    running_peak = wealth.cummax()
    drawdowns = wealth / running_peak - 1.0
    max_drawdown = float(drawdowns.min())
    cutoff = float(drawdowns.quantile(0.05))
    tail = drawdowns.loc[drawdowns <= cutoff]
    cdar_95 = float(tail.mean()) if len(tail) else 0.0
    return PerformanceMetrics(
        observations=len(values),
        annualized_return=annualized_return,
        annualized_volatility=annualized_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        cdar_95=cdar_95,
        hit_rate=float((values > 0).mean()),
    )


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    benchmark_daily_sharpe: float = 0.0,
) -> float:
    """Bailey/Lopez-de-Prado style PSR using sample skew and kurtosis."""

    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    n = len(values)
    if n < 3:
        raise ValueError("at least three returns are required")
    std = float(values.std(ddof=1))
    if std <= 0:
        return 0.0
    sr = float(values.mean()) / std
    skew = float(values.skew())
    kurt = float(values.kurt() + 3.0)  # pandas reports excess kurtosis
    denominator_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denominator_sq <= 0:
        return 0.0
    z = (sr - benchmark_daily_sharpe) * sqrt(n - 1) / sqrt(denominator_sq)
    return float(NormalDist().cdf(z))


def deflated_sharpe_ratio(returns: pd.Series, *, number_of_trials: int) -> float:
    """Conservative DSR approximation adjusting the benchmark for multiple trials."""

    if number_of_trials <= 0:
        raise ValueError("number_of_trials must be positive")
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    n = len(values)
    if n < 3:
        raise ValueError("at least three returns are required")
    if number_of_trials == 1:
        benchmark = 0.0
    else:
        # Expected maximum of N approximately-normal null Sharpe estimates.
        gamma = 0.5772156649015329
        normal = NormalDist()
        p1 = 1.0 - 1.0 / number_of_trials
        p2 = 1.0 - 1.0 / (number_of_trials * exp(1.0))
        se = 1.0 / sqrt(n - 1)
        benchmark = se * (
            (1.0 - gamma) * normal.inv_cdf(p1) + gamma * normal.inv_cdf(p2)
        )
    return probabilistic_sharpe_ratio(values, benchmark_daily_sharpe=benchmark)


def _sharpe_unannualized(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(values) < 2:
        return float("-inf")
    std = float(values.std(ddof=1))
    return float(values.mean()) / std if std > 0 else float("-inf")


def probability_of_backtest_overfitting(
    strategy_returns: pd.DataFrame,
    *,
    blocks: int = 10,
) -> float:
    """Estimate PBO with combinatorially-symmetric cross-validation (CSCV).

    Columns are competing strategy/configuration return streams. The time axis is
    split into an even number of contiguous blocks. For each half-block in-sample
    combination, the best in-sample strategy is ranked on the complementary OOS
    sample. PBO is the fraction whose OOS rank is below the median.
    """

    frame = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if frame.shape[1] < 2:
        raise ValueError("PBO requires at least two strategies")
    if blocks < 4 or blocks % 2:
        raise ValueError("blocks must be an even integer >= 4")
    if len(frame) < blocks * 2:
        raise ValueError("not enough observations for requested CSCV blocks")

    indices = list(range(len(frame)))
    block_members = [list(map(int, chunk)) for chunk in pd.Series(indices).groupby(pd.Series(indices) * blocks // len(indices)).apply(list)]
    # Defensive normalization in case integer grouping produces a boundary quirk.
    block_members = [block for block in block_members if block]
    if len(block_members) != blocks:
        block_members = [
            indices[(i * len(indices)) // blocks : ((i + 1) * len(indices)) // blocks]
            for i in range(blocks)
        ]

    below_median = 0
    total = 0
    all_blocks = set(range(blocks))
    for selected in combinations(range(blocks), blocks // 2):
        # Symmetric complements duplicate the same partition; keep one canonical side.
        complement = tuple(sorted(all_blocks - set(selected)))
        if selected > complement:
            continue
        in_rows = [row for block in selected for row in block_members[block]]
        out_rows = [row for block in complement for row in block_members[block]]
        in_scores = frame.iloc[in_rows].apply(_sharpe_unannualized, axis=0)
        winner = str(in_scores.idxmax())
        out_scores = frame.iloc[out_rows].apply(_sharpe_unannualized, axis=0)
        # Percentile rank in [0,1], where 1 is best. Ties get average rank.
        percentile = float(out_scores.rank(pct=True, method="average")[winner])
        below_median += int(percentile <= 0.5)
        total += 1
    return below_median / total if total else 1.0


def whites_reality_check(
    strategy_returns: pd.DataFrame,
    *,
    bootstrap_samples: int = 1000,
    block_size: int = 5,
    seed: int = 0,
) -> float:
    """Block-bootstrap White Reality Check p-value for the best mean strategy.

    Returns are centered strategy-by-strategy under the null. The bootstrap
    statistic is the maximum mean across strategies, controlling data snooping.
    """

    frame = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if frame.empty or frame.shape[1] < 2:
        raise ValueError("Reality Check requires non-empty returns for >=2 strategies")
    if bootstrap_samples <= 0 or block_size <= 0:
        raise ValueError("bootstrap_samples and block_size must be positive")
    observed = float(frame.mean(axis=0).max())
    centered = frame - frame.mean(axis=0)
    n = len(centered)
    rng = Random(seed)
    exceed = 0
    for _ in range(bootstrap_samples):
        rows: list[int] = []
        while len(rows) < n:
            start = rng.randrange(n)
            rows.extend((start + offset) % n for offset in range(block_size))
        sample = centered.iloc[rows[:n]]
        statistic = float(sample.mean(axis=0).max())
        exceed += int(statistic >= observed)
    return (exceed + 1.0) / (bootstrap_samples + 1.0)

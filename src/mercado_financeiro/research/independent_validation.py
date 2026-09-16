from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class IndependentMultipleComparisonResult:
    observations: int
    strategies: int
    spa_lower_pvalue: float
    spa_consistent_pvalue: float
    spa_upper_pvalue: float
    spa_better_models: tuple[str, ...]
    mcs_included_models: tuple[str, ...]
    mcs_pvalues: pd.DataFrame


def _clean_strategy_returns(strategy_returns: pd.DataFrame) -> pd.DataFrame:
    frame = strategy_returns.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if frame.shape[1] < 2:
        raise ValueError("independent validation requires at least two strategies")
    if len(frame) < 20:
        raise ValueError("independent validation requires at least 20 observations")
    if frame.columns.duplicated().any():
        raise ValueError("strategy names must be unique")
    return frame.astype(float)


def independent_spa_mcs_validation(
    strategy_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.Series | None = None,
    block_size: int = 10,
    bootstrap_reps: int = 1000,
    mcs_size: float = 0.10,
    seed: int = 0,
) -> IndependentMultipleComparisonResult:
    """Cross-check Tournament selection with the independent ``arch`` package.

    Mercado Financeiro keeps its own deterministic White Reality Check/PBO/DSR
    implementation. This function is intentionally a second implementation using
    ``arch.bootstrap``'s Hansen SPA and Model Confidence Set. It does not replace the
    canonical Tournament engine; disagreement is evidence to investigate.

    Returns are converted to losses by negation because SPA/MCS are defined in terms
    of lower loss being better.
    """
    if block_size <= 0 or bootstrap_reps <= 0:
        raise ValueError("block_size and bootstrap_reps must be positive")
    if not 0 < mcs_size < 1:
        raise ValueError("mcs_size must be in (0,1)")

    frame = _clean_strategy_returns(strategy_returns)
    if benchmark_returns is None:
        benchmark = pd.Series(0.0, index=frame.index, name="benchmark")
    else:
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce")
        benchmark = benchmark.reindex(frame.index)
        if benchmark.isna().any():
            raise ValueError("benchmark returns must cover every strategy observation")
        benchmark = benchmark.astype(float)

    try:
        from arch.bootstrap.multiple_comparison import MCS, SPA
    except ImportError as exc:  # pragma: no cover - dependency gate catches this
        raise RuntimeError(
            "independent validation requires optional dependency: pip install '.[validation]'"
        ) from exc

    benchmark_losses = -benchmark
    model_losses = -frame

    spa = SPA(
        benchmark_losses,
        model_losses,
        block_size=block_size,
        reps=bootstrap_reps,
        seed=seed,
    )
    spa.compute()
    pvalues = spa.pvalues
    better_indices = spa.better_models(pvalue=0.05, pvalue_type="consistent")
    column_names = list(map(str, frame.columns))
    better_models = tuple(column_names[int(index)] for index in better_indices)

    mcs = MCS(
        model_losses,
        size=mcs_size,
        reps=bootstrap_reps,
        block_size=block_size,
        seed=seed,
    )
    mcs.compute()
    included = tuple(str(value) for value in mcs.included)

    return IndependentMultipleComparisonResult(
        observations=len(frame),
        strategies=frame.shape[1],
        spa_lower_pvalue=float(pvalues["lower"]),
        spa_consistent_pvalue=float(pvalues["consistent"]),
        spa_upper_pvalue=float(pvalues["upper"]),
        spa_better_models=better_models,
        mcs_included_models=included,
        mcs_pvalues=mcs.pvalues.copy(),
    )

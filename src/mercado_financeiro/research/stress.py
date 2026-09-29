from __future__ import annotations

from dataclasses import dataclass
from random import Random

import pandas as pd


@dataclass(frozen=True)
class MonteCarloStressResult:
    paths: int
    horizon: int
    block_size: int
    terminal_return_p05: float
    terminal_return_median: float
    terminal_return_p95: float
    worst_max_drawdown: float


@dataclass(frozen=True)
class HistoricalStressResult:
    observations: int
    cumulative_return: float
    max_drawdown: float


def _max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    if wealth.empty:
        return 0.0
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def block_bootstrap_stress(
    returns: pd.Series,
    *,
    paths: int = 1000,
    horizon: int = 252,
    block_size: int = 5,
    seed: int = 0,
) -> MonteCarloStressResult:
    """Historical block-bootstrap stress test; not a price forecast."""

    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float).reset_index(drop=True)
    if len(values) < max(20, block_size):
        raise ValueError("insufficient historical returns")
    if (values <= -1.0).any():
        raise ValueError("returns cannot be <= -100%")
    if paths <= 0 or horizon <= 0 or block_size <= 0:
        raise ValueError("paths, horizon and block_size must be positive")

    rng = Random(seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    n = len(values)
    for _ in range(paths):
        sampled: list[float] = []
        while len(sampled) < horizon:
            start = rng.randrange(n)
            sampled.extend(float(values.iloc[(start + offset) % n]) for offset in range(block_size))
        path = pd.Series(sampled[:horizon], dtype=float)
        terminals.append(float((1.0 + path).prod() - 1.0))
        drawdowns.append(_max_drawdown(path))

    terminal = pd.Series(terminals, dtype=float)
    return MonteCarloStressResult(
        paths=paths,
        horizon=horizon,
        block_size=block_size,
        terminal_return_p05=float(terminal.quantile(0.05)),
        terminal_return_median=float(terminal.quantile(0.50)),
        terminal_return_p95=float(terminal.quantile(0.95)),
        worst_max_drawdown=float(min(drawdowns)),
    )


def historical_window_stress(
    returns: pd.Series,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> HistoricalStressResult:
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("historical stress requires a DatetimeIndex")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts < start_ts:
        raise ValueError("stress interval is invalid")
    values = pd.to_numeric(returns.loc[start_ts:end_ts], errors="coerce").dropna().astype(float)
    if values.empty:
        raise ValueError("historical stress window has no observations")
    if (values <= -1.0).any():
        raise ValueError("returns cannot be <= -100%")
    return HistoricalStressResult(
        observations=len(values),
        cumulative_return=float((1.0 + values).prod() - 1.0),
        max_drawdown=_max_drawdown(values),
    )


__all__ = [
    "HistoricalStressResult",
    "MonteCarloStressResult",
    "block_bootstrap_stress",
    "historical_window_stress",
]

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ResearchStrategySpec:
    strategy_id: str
    version: str
    factor: str
    horizon_days: tuple[int, int]
    hypothesis: str
    required_features: tuple[str, ...]
    universe: str = "B3_PIT_LIQUID_EQUITIES_ETFS"
    long_only: bool = True

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.version.strip():
            raise ValueError("strategy_id/version are required")
        start, end = self.horizon_days
        if start <= 0 or end < start:
            raise ValueError("invalid strategy horizon")
        if not self.hypothesis.strip() or not self.required_features:
            raise ValueError("hypothesis and required_features are required")


DEFAULT_RESEARCH_CATALOG: Mapping[str, ResearchStrategySpec] = {
    "value": ResearchStrategySpec(
        strategy_id="factor_value",
        version="1.0.0",
        factor="value",
        horizon_days=(5, 60),
        hypothesis="Relatively inexpensive securities may earn a return premium after controlling for PIT availability and trading costs.",
        required_features=("earnings_yield", "book_to_market"),
    ),
    "momentum": ResearchStrategySpec(
        strategy_id="factor_momentum",
        version="1.0.0",
        factor="momentum",
        horizon_days=(5, 60),
        hypothesis="Medium-term relative price persistence may continue after implementation costs and PIT controls.",
        required_features=("momentum_63", "momentum_252"),
    ),
    "quality": ResearchStrategySpec(
        strategy_id="factor_quality",
        version="1.0.0",
        factor="quality",
        horizon_days=(5, 60),
        hypothesis="More profitable and financially robust issuers may have different future return distributions after PIT controls.",
        required_features=("roe", "gross_profitability"),
    ),
    "low_risk": ResearchStrategySpec(
        strategy_id="factor_low_risk",
        version="1.0.0",
        factor="low_risk",
        horizon_days=(5, 60),
        hypothesis="Lower-risk securities may deliver different risk-adjusted outcomes than higher-risk peers.",
        required_features=("volatility_63", "beta_252"),
    ),
    "liquidity": ResearchStrategySpec(
        strategy_id="factor_liquidity",
        version="1.0.0",
        factor="liquidity",
        horizon_days=(5, 60),
        hypothesis="Liquidity characteristics may carry a return/capacity trade-off that must be measured net of implementation costs.",
        required_features=("adv_21", "turnover_21"),
    ),
}


def get_research_strategy(name: str) -> ResearchStrategySpec:
    try:
        return DEFAULT_RESEARCH_CATALOG[name.strip().lower()]
    except KeyError as exc:
        raise KeyError(f"unknown canonical research strategy: {name}") from exc


__all__ = ["DEFAULT_RESEARCH_CATALOG", "ResearchStrategySpec", "get_research_strategy"]

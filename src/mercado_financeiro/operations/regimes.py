from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class RegimeThresholds:
    high_volatility: Decimal = Decimal("0.25")
    low_volatility: Decimal = Decimal("0.15")
    rate_change: Decimal = Decimal("0.005")
    inflation_z: Decimal = Decimal("1.0")

    def __post_init__(self) -> None:
        if self.low_volatility < 0 or self.high_volatility <= self.low_volatility:
            raise ValueError("volatility thresholds are invalid")
        if self.rate_change <= 0 or self.inflation_z <= 0:
            raise ValueError("rate_change and inflation_z must be positive")


@dataclass(frozen=True)
class MarketRegime:
    risk: Literal["risk_on", "risk_off"]
    volatility: Literal["high", "normal", "low"]
    rates: Literal["rising", "stable", "falling"]
    inflation: Literal["high", "normal", "low"]


def classify_market_regime(
    *,
    broad_market_return: Decimal,
    annualized_volatility: Decimal,
    rate_change_3m: Decimal,
    inflation_zscore: Decimal,
    thresholds: RegimeThresholds | None = None,
) -> MarketRegime:
    cfg = thresholds or RegimeThresholds()
    if annualized_volatility < 0:
        raise ValueError("annualized_volatility cannot be negative")

    if annualized_volatility >= cfg.high_volatility:
        volatility = "high"
    elif annualized_volatility <= cfg.low_volatility:
        volatility = "low"
    else:
        volatility = "normal"

    if rate_change_3m >= cfg.rate_change:
        rates = "rising"
    elif rate_change_3m <= -cfg.rate_change:
        rates = "falling"
    else:
        rates = "stable"

    if inflation_zscore >= cfg.inflation_z:
        inflation = "high"
    elif inflation_zscore <= -cfg.inflation_z:
        inflation = "low"
    else:
        inflation = "normal"

    risk = "risk_on" if broad_market_return > 0 and volatility != "high" else "risk_off"
    return MarketRegime(
        risk=risk,
        volatility=volatility,
        rates=rates,
        inflation=inflation,
    )

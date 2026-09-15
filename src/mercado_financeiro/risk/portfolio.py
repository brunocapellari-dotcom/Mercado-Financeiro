from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class PortfolioRiskLimits:
    max_gross_exposure_fraction: Decimal = Decimal("1.00")
    max_abs_net_exposure_fraction: Decimal = Decimal("0.50")
    max_sector_exposure_fraction: Decimal = Decimal("0.25")
    max_abs_beta: Decimal = Decimal("1.50")
    max_abs_factor_exposure: Decimal = Decimal("3.00")
    max_correlation_cluster_fraction: Decimal = Decimal("0.35")
    max_capacity_utilization: Decimal = Decimal("0.80")

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class PortfolioRiskSnapshot:
    equity: Decimal
    gross_notional: Decimal
    net_notional: Decimal
    sector_notionals: Mapping[str, Decimal]
    factor_exposures: Mapping[str, Decimal]
    beta: Decimal
    largest_correlation_cluster_notional: Decimal
    capacity_utilization: Decimal

    def __post_init__(self) -> None:
        if self.equity <= 0:
            raise ValueError("equity must be positive")
        if self.gross_notional < 0:
            raise ValueError("gross_notional cannot be negative")
        if self.largest_correlation_cluster_notional < 0:
            raise ValueError("largest_correlation_cluster_notional cannot be negative")
        if self.capacity_utilization < 0:
            raise ValueError("capacity_utilization cannot be negative")
        if any(value < 0 for value in self.sector_notionals.values()):
            raise ValueError("sector notionals must be non-negative absolute exposures")


@dataclass(frozen=True)
class PortfolioRiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    gross_exposure_fraction: Decimal
    net_exposure_fraction: Decimal
    largest_sector_fraction: Decimal
    correlation_cluster_fraction: Decimal


class DeterministicPortfolioRiskEngine:
    """Independent deterministic portfolio-level risk veto."""

    def __init__(self, limits: PortfolioRiskLimits | None = None) -> None:
        self._limits = limits or PortfolioRiskLimits()

    def evaluate(self, snapshot: PortfolioRiskSnapshot) -> PortfolioRiskDecision:
        equity = snapshot.equity
        gross = snapshot.gross_notional / equity
        net = snapshot.net_notional / equity
        largest_sector = (
            max(snapshot.sector_notionals.values(), default=Decimal("0")) / equity
        )
        cluster = snapshot.largest_correlation_cluster_notional / equity
        reasons: list[str] = []

        if gross > self._limits.max_gross_exposure_fraction:
            reasons.append("max_gross_exposure_exceeded")
        if abs(net) > self._limits.max_abs_net_exposure_fraction:
            reasons.append("max_net_exposure_exceeded")
        if largest_sector > self._limits.max_sector_exposure_fraction:
            reasons.append("max_sector_exposure_exceeded")
        if abs(snapshot.beta) > self._limits.max_abs_beta:
            reasons.append("max_beta_exceeded")
        factor_breaches = sorted(
            name
            for name, exposure in snapshot.factor_exposures.items()
            if abs(exposure) > self._limits.max_abs_factor_exposure
        )
        if factor_breaches:
            reasons.extend(f"factor_exposure_exceeded:{name}" for name in factor_breaches)
        if cluster > self._limits.max_correlation_cluster_fraction:
            reasons.append("max_correlation_cluster_exceeded")
        if snapshot.capacity_utilization > self._limits.max_capacity_utilization:
            reasons.append("capacity_limit_exceeded")

        return PortfolioRiskDecision(
            approved=not reasons,
            reasons=tuple(reasons),
            gross_exposure_fraction=gross,
            net_exposure_fraction=net,
            largest_sector_fraction=largest_sector,
            correlation_cluster_fraction=cluster,
        )

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class AttributionRecord:
    asset: str
    sector: str
    factor: str
    strategy: str
    period: str
    decision: str
    gross_pnl: Decimal
    costs: Decimal

    def __post_init__(self) -> None:
        for name in ("asset", "sector", "factor", "strategy", "period", "decision"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.costs < 0:
            raise ValueError("costs cannot be negative")

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.costs


@dataclass(frozen=True)
class AttributionReport:
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    by_asset: tuple[tuple[str, Decimal], ...]
    by_sector: tuple[tuple[str, Decimal], ...]
    by_factor: tuple[tuple[str, Decimal], ...]
    by_strategy: tuple[tuple[str, Decimal], ...]
    by_period: tuple[tuple[str, Decimal], ...]
    by_decision: tuple[tuple[str, Decimal], ...]


def _group(records: tuple[AttributionRecord, ...], field: str) -> tuple[tuple[str, Decimal], ...]:
    totals: dict[str, Decimal] = {}
    for record in records:
        key = str(getattr(record, field))
        totals[key] = totals.get(key, Decimal("0")) + record.net_pnl
    return tuple(sorted(totals.items()))


def build_attribution(records: Iterable[AttributionRecord]) -> AttributionReport:
    materialized = tuple(records)
    gross = sum((record.gross_pnl for record in materialized), Decimal("0"))
    costs = sum((record.costs for record in materialized), Decimal("0"))
    net = gross - costs
    report = AttributionReport(
        gross_pnl=gross,
        costs=costs,
        net_pnl=net,
        by_asset=_group(materialized, "asset"),
        by_sector=_group(materialized, "sector"),
        by_factor=_group(materialized, "factor"),
        by_strategy=_group(materialized, "strategy"),
        by_period=_group(materialized, "period"),
        by_decision=_group(materialized, "decision"),
    )
    for grouped in (
        report.by_asset,
        report.by_sector,
        report.by_factor,
        report.by_strategy,
        report.by_period,
        report.by_decision,
    ):
        if sum((value for _, value in grouped), Decimal("0")) != net:
            raise RuntimeError("attribution does not reconcile to portfolio net P&L")
    return report

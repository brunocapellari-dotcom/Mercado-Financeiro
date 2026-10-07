from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


class IngestionLane(str, Enum):
    CURRENT = "current"
    BACKFILL = "backfill"


@dataclass(frozen=True)
class IngestionWindow:
    source: str
    dataset: str
    lane: IngestionLane
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.dataset.strip():
            raise ValueError("source and dataset are required")
        if self.end < self.start:
            raise ValueError("end cannot precede start")


@dataclass(frozen=True)
class IngestionPlan:
    current: IngestionWindow
    backfill: tuple[IngestionWindow, ...]

    def __post_init__(self) -> None:
        if self.current.lane is not IngestionLane.CURRENT:
            raise ValueError("current lane must be CURRENT")
        if any(window.lane is not IngestionLane.BACKFILL for window in self.backfill):
            raise ValueError("historical windows must be BACKFILL")
        if any(window.end >= self.current.start for window in self.backfill):
            raise ValueError("backfill cannot overlap the current-ingestion window")


def yearly_windows(
    *,
    source: str,
    dataset: str,
    start: date,
    end: date,
) -> tuple[IngestionWindow, ...]:
    if end < start:
        return ()
    windows: list[IngestionWindow] = []
    year = start.year
    while year <= end.year:
        first = max(start, date(year, 1, 1))
        last = min(end, date(year, 12, 31))
        windows.append(
            IngestionWindow(
                source=source,
                dataset=dataset,
                lane=IngestionLane.BACKFILL,
                start=first,
                end=last,
            )
        )
        year += 1
    return tuple(windows)


def plan_current_with_backfill(
    *,
    source: str,
    dataset: str,
    current_date: date,
    history_start: date = date(2001, 1, 2),
) -> IngestionPlan:
    if current_date < history_start:
        raise ValueError("current_date cannot precede history_start")
    current = IngestionWindow(
        source=source,
        dataset=dataset,
        lane=IngestionLane.CURRENT,
        start=current_date,
        end=current_date,
    )
    history_end = current_date - timedelta(days=1)
    return IngestionPlan(
        current=current,
        backfill=yearly_windows(
            source=source,
            dataset=dataset,
            start=history_start,
            end=history_end,
        ),
    )

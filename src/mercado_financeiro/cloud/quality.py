from __future__ import annotations

from dataclasses import dataclass
import pandas as pd
from .snapshot_diff import SnapshotDiff

@dataclass(frozen=True)
class DataSLA:
    max_age: pd.Timedelta
    min_rows: int = 1
    max_row_drop_fraction: float = 0.25
    allow_schema_change: bool = False
    def __post_init__(self) -> None:
        if self.max_age <= pd.Timedelta(0):
            raise ValueError("max_age must be positive")
        if self.min_rows < 0 or not 0 <= self.max_row_drop_fraction <= 1:
            raise ValueError("invalid data SLA")

@dataclass(frozen=True)
class DataSLAResult:
    approved: bool
    reasons: tuple[str, ...]

def evaluate_data_sla(*, observed_at, now, current_rows: int, previous_rows: int | None, diff: SnapshotDiff | None, sla: DataSLA) -> DataSLAResult:
    observed = pd.to_datetime(observed_at, errors="raise", utc=True)
    current = pd.to_datetime(now, errors="raise", utc=True)
    reasons: list[str] = []
    if observed > current:
        reasons.append("future_observation_time")
    elif current - observed > sla.max_age:
        reasons.append("stale")
    if current_rows < sla.min_rows:
        reasons.append("row_count_below_minimum")
    if previous_rows is not None and previous_rows > 0:
        if max(0, previous_rows - current_rows) / previous_rows > sla.max_row_drop_fraction:
            reasons.append("row_count_drop")
    if diff is not None:
        if diff.duplicate_current_keys:
            reasons.append("duplicate_keys")
        if not sla.allow_schema_change and (diff.added_columns or diff.removed_columns):
            reasons.append("schema_drift")
    return DataSLAResult(not reasons, tuple(reasons))

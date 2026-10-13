from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class DataQualityContract:
    """Fail-closed structural and temporal contract for a canonical dataset."""

    name: str
    required_columns: tuple[str, ...]
    not_null_columns: tuple[str, ...] = ()
    unique_key: tuple[str, ...] = ()
    timestamp_column: str | None = None
    max_age: timedelta | None = None
    monotonic_group_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("contract name is required")
        if len(self.required_columns) != len(set(self.required_columns)):
            raise ValueError("required_columns must be unique")
        required = set(self.required_columns)
        for group in (self.not_null_columns, self.unique_key, self.monotonic_group_keys):
            if not set(group).issubset(required):
                raise ValueError("quality constraints must reference required columns")
        if self.timestamp_column is not None and self.timestamp_column not in required:
            raise ValueError("timestamp_column must be required")
        if self.max_age is not None:
            if self.timestamp_column is None:
                raise ValueError("max_age requires timestamp_column")
            if self.max_age <= timedelta(0):
                raise ValueError("max_age must be positive")


@dataclass(frozen=True)
class DataQualityResult:
    passed: bool
    violations: tuple[str, ...]
    metrics: tuple[tuple[str, float], ...]


def evaluate_data_quality(
    frame: pd.DataFrame,
    contract: DataQualityContract,
    *,
    as_of: pd.Timestamp | None = None,
    minimum_rows: int = 1,
    numeric_ranges: Mapping[str, tuple[float | None, float | None]] | None = None,
) -> DataQualityResult:
    if minimum_rows < 0:
        raise ValueError("minimum_rows cannot be negative")
    violations: list[str] = []
    metrics: dict[str, float] = {"rows": float(len(frame))}
    missing = set(contract.required_columns) - set(frame.columns)
    if missing:
        violations.append("missing_columns=" + ",".join(sorted(missing)))
        return DataQualityResult(False, tuple(violations), tuple(sorted(metrics.items())))
    if len(frame) < minimum_rows:
        violations.append(f"rows={len(frame)}<minimum={minimum_rows}")

    for column in contract.not_null_columns:
        count = int(frame[column].isna().sum())
        metrics[f"nulls:{column}"] = float(count)
        if count:
            violations.append(f"nulls:{column}={count}")

    if contract.unique_key:
        duplicates = int(frame.duplicated(list(contract.unique_key), keep=False).sum())
        metrics["duplicate_rows"] = float(duplicates)
        if duplicates:
            violations.append(f"duplicate_rows={duplicates}")

    timestamp: pd.Series | None = None
    if contract.timestamp_column is not None:
        timestamp = pd.to_datetime(frame[contract.timestamp_column], errors="coerce", utc=True)
        invalid_ts = int(timestamp.isna().sum())
        metrics["invalid_timestamps"] = float(invalid_ts)
        if invalid_ts:
            violations.append(f"invalid_timestamps={invalid_ts}")
        if as_of is not None:
            cutoff = pd.Timestamp(as_of)
            if cutoff.tzinfo is None:
                raise ValueError("as_of must be timezone-aware")
            cutoff = cutoff.tz_convert("UTC")
            future = int((timestamp.notna() & (timestamp > cutoff)).sum())
            metrics["future_rows"] = float(future)
            if future:
                violations.append(f"future_rows={future}")
            if contract.max_age is not None and timestamp.notna().any():
                stale_cutoff = cutoff - contract.max_age
                latest = timestamp.max()
                age_seconds = float((cutoff - latest).total_seconds())
                metrics["latest_age_seconds"] = age_seconds
                if latest < stale_cutoff:
                    violations.append(
                        f"stale_latest={latest.isoformat()} cutoff={stale_cutoff.isoformat()}"
                    )

    if contract.monotonic_group_keys and timestamp is not None:
        work = frame[list(contract.monotonic_group_keys)].copy()
        work["__timestamp"] = timestamp
        non_monotonic = 0
        for _, group in work.groupby(list(contract.monotonic_group_keys), sort=False, dropna=False):
            values = group["__timestamp"].dropna()
            if not values.is_monotonic_increasing:
                non_monotonic += 1
        metrics["non_monotonic_groups"] = float(non_monotonic)
        if non_monotonic:
            violations.append(f"non_monotonic_groups={non_monotonic}")

    for column, bounds in (numeric_ranges or {}).items():
        if column not in frame.columns:
            violations.append(f"range_column_missing={column}")
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid = int(values.isna().sum() - frame[column].isna().sum())
        if invalid:
            violations.append(f"non_numeric:{column}={invalid}")
        lower, upper = bounds
        out_of_range = pd.Series(False, index=frame.index)
        if lower is not None:
            out_of_range |= values < lower
        if upper is not None:
            out_of_range |= values > upper
        count = int(out_of_range.fillna(False).sum())
        metrics[f"out_of_range:{column}"] = float(count)
        if count:
            violations.append(f"out_of_range:{column}={count}")

    return DataQualityResult(
        passed=not violations,
        violations=tuple(violations),
        metrics=tuple(sorted(metrics.items())),
    )


def assert_data_quality(*args, **kwargs) -> DataQualityResult:
    result = evaluate_data_quality(*args, **kwargs)
    if not result.passed:
        raise RuntimeError("data quality gate failed: " + "; ".join(result.violations))
    return result

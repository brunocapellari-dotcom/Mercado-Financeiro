from __future__ import annotations

from datetime import timedelta

import pandas as pd


def assert_feature_freshness(
    frame: pd.DataFrame,
    *,
    event_timestamp_column: str,
    source_timestamp_column: str,
    max_age: timedelta,
    allow_missing_source: bool = False,
) -> None:
    """Reject look-ahead and stale feature values at their consumption time.

    This is the temporal counterpart to a feature schema: the same feature can be
    structurally valid yet operationally unsafe when its source observation is too
    old. Source timestamps must never be after or equal to the event timestamp.
    """

    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    missing = {event_timestamp_column, source_timestamp_column} - set(frame.columns)
    if missing:
        raise ValueError(f"missing freshness columns: {sorted(missing)}")
    event = pd.to_datetime(frame[event_timestamp_column], errors="coerce", utc=True)
    source = pd.to_datetime(frame[source_timestamp_column], errors="coerce", utc=True)
    if event.isna().any():
        raise ValueError("invalid event timestamps")
    if not allow_missing_source and source.isna().any():
        raise RuntimeError(f"missing feature source timestamps: {int(source.isna().sum())}")
    known = source.notna()
    future = known & (source >= event)
    if future.any():
        raise RuntimeError(f"feature look-ahead detected on {int(future.sum())} rows")
    stale = known & ((event - source) > max_age)
    if stale.any():
        raise RuntimeError(f"stale feature values detected on {int(stale.sum())} rows")

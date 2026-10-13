from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import pandas as pd


class VintageMode(str, Enum):
    EXACT_VINTAGE = "exact_vintage"
    PUBLICATION_GATED = "publication_gated"
    CONSERVATIVE_RETRIEVAL = "conservative_retrieval"
    BENCHMARK_ONLY = "benchmark_only"


@dataclass(frozen=True)
class HistoricalDataset:
    source: str
    dataset: str
    source_url: str
    retrieved_at: datetime
    sha256: str
    vintage_mode: VintageMode
    frame: pd.DataFrame
    raw_receipt_id: str | None = None

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if len(self.sha256) != 64:
            raise ValueError("sha256 must be a 64-character hex digest")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("sha256 must be hexadecimal") from exc
        if not self.source.strip() or not self.dataset.strip():
            raise ValueError("source and dataset are required")
        if self.raw_receipt_id is not None:
            receipt = self.raw_receipt_id.strip().lower()
            if len(receipt) != 64 or any(ch not in "0123456789abcdef" for ch in receipt):
                raise ValueError("raw_receipt_id must be a 64-character hexadecimal digest")

    @property
    def retrieved_at_utc(self) -> datetime:
        return self.retrieved_at.astimezone(timezone.utc)


class HistoricalDataSource(Protocol):
    name: str

    def healthcheck(self) -> bool:
        ...


def require_pit_columns(frame: pd.DataFrame) -> None:
    """Require valid event/reference and information-availability timestamps.

    The generic PIT contract deliberately does *not* impose
    ``available_from >= reference_date``. Some legitimate market/macro observations
    are announcements about a future effective/reference date (for example a policy
    target known before its effective date). Look-ahead safety is governed by
    ``available_from``. Domain-specific datasets such as financial statements may
    impose the stronger ordering in their own validators.
    """

    required = {"reference_date", "available_from"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"historical dataset missing PIT columns: {sorted(missing)}")
    reference = pd.to_datetime(frame["reference_date"], errors="coerce", utc=True)
    available = pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
    if reference.isna().any() or available.isna().any():
        raise ValueError("invalid reference_date/available_from in historical dataset")


def asof(frame: pd.DataFrame, cutoff: str | pd.Timestamp) -> pd.DataFrame:
    """Return only observations known by cutoff.

    This helper deliberately requires an explicit ``available_from`` column so a
    reference/effective date can never be mistaken for an information-availability
    date. Announced future-effective observations remain valid if they were genuinely
    known by the cutoff.
    """

    require_pit_columns(frame)
    cutoff_ts = pd.to_datetime(cutoff, errors="raise", utc=True)
    available = pd.to_datetime(frame["available_from"], errors="raise", utc=True)
    return frame.loc[available <= cutoff_ts].copy().reset_index(drop=True)

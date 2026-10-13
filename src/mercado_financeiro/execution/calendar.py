from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class B3SessionCalendarAudit:
    sessions: int
    first_session: pd.Timestamp
    last_session: pd.Timestamp
    weekend_sessions: int
    duplicate_sessions: int
    source_sha256: str


class ObservedB3SettlementCalendar:
    """Settlement calendar derived from observed official B3 trading sessions.

    Historical research must not infer weekdays as exchange sessions: Brazilian
    holidays, Carnival, ad-hoc closures and historical calendar changes matter.
    The calendar therefore accepts the dates actually observed in an official B3
    source such as COTAHIST.  It fails closed when asked to settle beyond the
    observed coverage rather than inventing future business days.

    The object satisfies ``execution.brokerage.SettlementCalendar``.  ``verified``
    is true only for a calendar constructed through ``from_observed_sessions`` after
    deterministic validation.
    """

    verified = True

    def __init__(
        self,
        sessions: pd.DatetimeIndex,
        *,
        source_sha256: str,
        source_name: str,
    ) -> None:
        if not source_name.strip():
            raise ValueError("source_name is required")
        digest = source_sha256.lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        normalized = pd.DatetimeIndex(pd.to_datetime(sessions, errors="coerce"))
        if normalized.isna().any():
            raise ValueError("sessions contain invalid dates")
        if normalized.tz is not None:
            normalized = normalized.tz_localize(None)
        normalized = normalized.normalize()
        duplicate_count = int(normalized.duplicated().sum())
        if duplicate_count:
            raise ValueError("observed B3 sessions must be unique")
        normalized = normalized.sort_values()
        if len(normalized) < 2:
            raise ValueError("at least two observed B3 sessions are required")
        weekend_count = int((normalized.dayofweek >= 5).sum())
        if weekend_count:
            raise ValueError("observed B3 sessions cannot fall on weekends")
        self._sessions = normalized
        self._source_sha256 = digest
        self._source_name = source_name
        self._audit = B3SessionCalendarAudit(
            sessions=len(normalized),
            first_session=normalized[0],
            last_session=normalized[-1],
            weekend_sessions=weekend_count,
            duplicate_sessions=duplicate_count,
            source_sha256=digest,
        )

    @classmethod
    def from_observed_sessions(
        cls,
        sessions: Iterable[object],
        *,
        source_bytes: bytes,
        source_name: str,
    ) -> "ObservedB3SettlementCalendar":
        if not source_bytes:
            raise ValueError("source_bytes are required for calendar provenance")
        return cls(
            pd.DatetimeIndex(pd.to_datetime(list(sessions), errors="coerce")),
            source_sha256=sha256(source_bytes).hexdigest(),
            source_name=source_name,
        )

    @classmethod
    def from_cotahist_quotes(
        cls,
        quotes: pd.DataFrame,
        *,
        source_bytes: bytes,
        source_name: str,
    ) -> "ObservedB3SettlementCalendar":
        if "trade_date" not in quotes.columns:
            raise ValueError("COTAHIST quotes require trade_date")
        sessions = pd.to_datetime(quotes["trade_date"], errors="coerce").dropna().drop_duplicates()
        return cls.from_observed_sessions(
            sessions,
            source_bytes=source_bytes,
            source_name=source_name,
        )

    @property
    def audit(self) -> B3SessionCalendarAudit:
        return self._audit

    @property
    def sessions(self) -> pd.DatetimeIndex:
        return self._sessions.copy()

    @property
    def source_name(self) -> str:
        return self._source_name

    def is_session(self, timestamp: datetime | pd.Timestamp) -> bool:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts.normalize() in self._sessions

    def add_business_days(self, timestamp: datetime, business_days: int) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("settlement timestamp must be timezone-aware")
        if business_days < 0:
            raise ValueError("business_days cannot be negative")
        if business_days == 0:
            return timestamp

        local_date = pd.Timestamp(timestamp).tz_localize(None).normalize()
        location = self._sessions.get_indexer([local_date])[0]
        if location < 0:
            raise RuntimeError("trade date is not an observed B3 session")
        target_location = location + business_days
        if target_location >= len(self._sessions):
            raise RuntimeError("settlement date exceeds verified B3 session coverage")
        target = self._sessions[target_location]
        return timestamp.replace(year=target.year, month=target.month, day=target.day)

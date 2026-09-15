from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Protocol


class ReplayStore(Protocol):
    """Atomic replay-protection boundary.

    Live implementations must persist uniqueness/TTL outside the process.
    """

    live_safe: bool

    def mark_if_new(
        self,
        event_id: str,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        """Atomically mark event_id as seen; return False if it already exists."""
        ...


class InMemoryReplayStore:
    """Thread-safe replay store for tests/paper only."""

    live_safe = False

    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}
        self._lock = RLock()

    def mark_if_new(
        self,
        event_id: str,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        expiry = expires_at.astimezone(timezone.utc)
        checked_at = now.astimezone(timezone.utc)
        with self._lock:
            expired = [key for key, value in self._seen.items() if value <= checked_at]
            for key in expired:
                self._seen.pop(key, None)
            if event_id in self._seen:
                return False
            self._seen[event_id] = expiry
            return True

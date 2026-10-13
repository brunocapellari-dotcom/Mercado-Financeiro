from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol


@dataclass(frozen=True)
class KillSwitchState:
    engaged: bool
    reason: str | None
    changed_at: datetime

    def __post_init__(self) -> None:
        if self.changed_at.tzinfo is None or self.changed_at.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        if self.engaged and not (self.reason or "").strip():
            raise ValueError("engaged kill switch requires a reason")


class KillSwitch(Protocol):
    """Independent source of truth for emergency execution disablement."""

    live_safe: bool

    def status(self) -> KillSwitchState:
        ...


class InMemoryKillSwitch:
    """Thread-safe reference switch for tests/paper; never sufficient for live."""

    live_safe = False

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = KillSwitchState(
            engaged=False,
            reason=None,
            changed_at=datetime.now(timezone.utc),
        )

    def status(self) -> KillSwitchState:
        with self._lock:
            return self._state

    def engage(self, reason: str, *, changed_at: datetime | None = None) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("kill switch reason is required")
        ts = changed_at or datetime.now(timezone.utc)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        state = KillSwitchState(True, reason.strip(), ts.astimezone(timezone.utc))
        with self._lock:
            self._state = state
        return state

    def reset(self, *, changed_at: datetime | None = None) -> KillSwitchState:
        ts = changed_at or datetime.now(timezone.utc)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        state = KillSwitchState(False, None, ts.astimezone(timezone.utc))
        with self._lock:
            self._state = state
        return state

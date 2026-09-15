from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .provider import FeedHealth, FeedStatus, MarketDataEvent, is_stale, sequence_gap


@dataclass
class LiveFeedMonitor:
    provider: str
    max_stale_seconds: float = 5.0
    connected: bool = False
    last_event: MarketDataEvent | None = None
    last_sequence: int | None = None
    gap_count: int = 0
    reconnect_count: int = 0

    def on_connect(self) -> None:
        if self.connected:
            return
        if self.last_event is not None:
            self.reconnect_count += 1
        self.connected = True

    def on_disconnect(self) -> None:
        self.connected = False

    def observe(self, event: MarketDataEvent) -> int:
        if event.provider != self.provider:
            raise ValueError("event provider does not match monitor provider")
        missing = sequence_gap(self.last_sequence, event.sequence)
        self.gap_count += missing
        self.last_sequence = event.sequence if event.sequence is not None else self.last_sequence
        self.last_event = event
        return missing

    def health(self, *, now: datetime | None = None) -> FeedHealth:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not self.connected:
            status = FeedStatus.DISCONNECTED
        elif self.last_event is None:
            status = FeedStatus.STALE
        elif self.gap_count:
            status = FeedStatus.GAP
        elif is_stale(self.last_event, now=checked_at, max_age_seconds=self.max_stale_seconds):
            status = FeedStatus.STALE
        else:
            status = FeedStatus.HEALTHY
        return FeedHealth(
            provider=self.provider,
            status=status,
            checked_at=checked_at,
            last_exchange_timestamp=self.last_event.exchange_timestamp if self.last_event else None,
            last_received_timestamp=self.last_event.received_timestamp if self.last_event else None,
            last_sequence=self.last_sequence,
            gap_count=self.gap_count,
            reconnect_count=self.reconnect_count,
        )

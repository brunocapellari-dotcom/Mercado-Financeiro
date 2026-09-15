from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Iterator


class FeedStatus(str, Enum):
    HEALTHY = "healthy"
    STALE = "stale"
    GAP = "gap"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class MarketDataEvent:
    provider: str
    instrument: str
    event_type: str
    exchange_timestamp: datetime
    received_timestamp: datetime
    sequence: int | None
    payload: object

    def __post_init__(self) -> None:
        for name, value in (
            ("exchange_timestamp", self.exchange_timestamp),
            ("received_timestamp", self.received_timestamp),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.received_timestamp < self.exchange_timestamp:
            raise ValueError("received_timestamp cannot precede exchange_timestamp")


@dataclass(frozen=True)
class FeedHealth:
    provider: str
    status: FeedStatus
    checked_at: datetime
    last_exchange_timestamp: datetime | None = None
    last_received_timestamp: datetime | None = None
    last_sequence: int | None = None
    gap_count: int = 0
    reconnect_count: int = 0
    details: str | None = None

    @classmethod
    def disconnected(cls, provider: str, details: str | None = None) -> "FeedHealth":
        return cls(
            provider=provider,
            status=FeedStatus.DISCONNECTED,
            checked_at=datetime.now(timezone.utc),
            details=details,
        )


class MarketDataProvider(ABC):
    """Vendor-neutral market-data boundary used by upper layers.

    Provider implementations own vendor authentication, reconnection and wire
    formats. Consumers receive normalized, timestamped events and provider
    health only.
    """

    name: str

    @abstractmethod
    def connect(self) -> None:
        """Establish or restore the provider connection."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the provider connection."""

    @abstractmethod
    def subscribe(self, instruments: Iterable[str]) -> Iterator[MarketDataEvent]:
        """Yield normalized events for the requested instruments."""

    @abstractmethod
    def snapshot(self, instruments: Iterable[str]) -> list[MarketDataEvent]:
        """Return a normalized point-in-time snapshot."""

    @abstractmethod
    def health(self) -> FeedHealth:
        """Return current feed health including stale/gap state."""


def sequence_gap(previous: int | None, current: int | None) -> int:
    """Return the number of missing sequence values, or zero when unknown."""

    if previous is None or current is None:
        return 0
    if current <= previous:
        return 0
    return max(0, current - previous - 1)


def is_stale(event: MarketDataEvent, *, now: datetime, max_age_seconds: float) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return (now - event.received_timestamp).total_seconds() > max_age_seconds

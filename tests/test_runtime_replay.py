from datetime import datetime, timedelta, timezone

import pytest

from mercado_financeiro.runtime import EventEnvelope, InMemoryEventBus
from mercado_financeiro.runtime.replay import (
    DeterministicReplayEngine,
    canonical_event_order,
    event_stream_digest,
)


def _event(event_id: str, second: int, sequence: int | None) -> EventEnvelope:
    occurred = datetime(2026, 9, 21, 12, 0, second, tzinfo=timezone.utc)
    return EventEnvelope(
        event_id=event_id,
        topic="market.tick",
        source="b3",
        occurred_at=occurred,
        received_at=occurred + timedelta(milliseconds=10),
        payload={"price": second},
        sequence=sequence,
    )


def test_replay_has_deterministic_total_order_and_digest():
    events = (
        _event("three", 3, 3),
        _event("one", 1, 1),
        _event("two", 2, 2),
    )
    ordered = canonical_event_order(events)
    assert [event.event_id for event in ordered] == ["one", "two", "three"]

    first = event_stream_digest(events)
    second = event_stream_digest(reversed(events))
    assert first == second

    seen: list[str] = []
    bus = InMemoryEventBus()
    bus.subscribe("market.tick", lambda event: seen.append(event.event_id))
    report = DeterministicReplayEngine().replay(events, event_bus=bus)

    assert seen == ["one", "two", "three"]
    assert report.events == 3
    assert report.stream_sha256 == first


def test_replay_rejects_duplicate_event_ids():
    event = _event("same", 1, 1)
    with pytest.raises(ValueError, match="duplicate event_id"):
        canonical_event_order((event, event))

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

from .kernel import EventBus, EventEnvelope


@dataclass(frozen=True)
class ReplayReport:
    events: int
    first_event_id: str | None
    last_event_id: str | None
    stream_sha256: str


def canonical_event_order(events: Iterable[EventEnvelope]) -> tuple[EventEnvelope, ...]:
    """Return one deterministic total ordering for replayable events."""

    materialized = tuple(events)
    ids = [event.event_id for event in materialized]
    if len(ids) != len(set(ids)):
        raise ValueError("replay stream contains duplicate event_id")

    return tuple(
        sorted(
            materialized,
            key=lambda event: (
                event.occurred_at,
                event.sequence if event.sequence is not None else 2**63 - 1,
                event.received_at,
                event.source,
                event.topic,
                event.event_id,
            ),
        )
    )


def event_stream_digest(events: Iterable[EventEnvelope]) -> str:
    ordered = canonical_event_order(events)
    rows: list[dict[str, object]] = []
    for event in ordered:
        payload = json.dumps(
            event.payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        rows.append(
            {
                "event_id": event.event_id,
                "topic": event.topic,
                "source": event.source,
                "occurred_at": event.occurred_at.isoformat(),
                "received_at": event.received_at.isoformat(),
                "sequence": event.sequence,
                "correlation_id": event.correlation_id,
                "payload_sha256": sha256(payload.encode("utf-8")).hexdigest(),
            }
        )
    encoded = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class DeterministicReplayEngine:
    """Small deterministic replay core shared by engine-parity benchmarks.

    It deliberately reuses the project EventEnvelope/EventBus contract rather than
    importing a second trading engine into the canonical runtime.
    """

    def replay(
        self,
        events: Iterable[EventEnvelope],
        *,
        event_bus: EventBus,
    ) -> ReplayReport:
        ordered = canonical_event_order(events)
        digest = event_stream_digest(ordered)
        for event in ordered:
            event_bus.publish(event)
        return ReplayReport(
            events=len(ordered),
            first_event_id=ordered[0].event_id if ordered else None,
            last_event_id=ordered[-1].event_id if ordered else None,
            stream_sha256=digest,
        )

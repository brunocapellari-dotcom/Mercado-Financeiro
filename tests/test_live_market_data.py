from datetime import datetime, timedelta, timezone

from mercado_financeiro.data import FeedStatus, LiveFeedMonitor, MarketDataEvent, sequence_gap


def _event(sequence: int, received: datetime) -> MarketDataEvent:
    return MarketDataEvent(
        provider="test-feed",
        instrument="PETR4",
        event_type="trade",
        exchange_timestamp=received - timedelta(milliseconds=10),
        received_timestamp=received,
        sequence=sequence,
        payload={"price": 32.1},
    )


def test_sequence_gap_detection():
    assert sequence_gap(10, 11) == 0
    assert sequence_gap(10, 14) == 3
    assert sequence_gap(None, 14) == 0
    assert sequence_gap(10, None) == 0


def test_live_monitor_detects_gap_stale_disconnect_and_reconnect():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    monitor = LiveFeedMonitor(provider="test-feed", max_stale_seconds=2.0)

    assert monitor.health(now=now).status is FeedStatus.DISCONNECTED
    monitor.on_connect()
    assert monitor.health(now=now).status is FeedStatus.STALE

    monitor.observe(_event(100, now))
    assert monitor.health(now=now).status is FeedStatus.HEALTHY

    assert monitor.observe(_event(103, now + timedelta(milliseconds=100))) == 2
    health = monitor.health(now=now + timedelta(milliseconds=200))
    assert health.status is FeedStatus.GAP
    assert health.gap_count == 2

    monitor.gap_count = 0
    assert monitor.health(now=now + timedelta(seconds=4)).status is FeedStatus.STALE

    monitor.on_disconnect()
    assert monitor.health(now=now + timedelta(seconds=5)).status is FeedStatus.DISCONNECTED
    monitor.on_connect()
    assert monitor.reconnect_count == 1

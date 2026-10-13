from datetime import datetime, timezone
import json

import pytest

from mercado_financeiro.data.brapi import BrapiMarketDataProvider
from mercado_financeiro.data.provider import FeedStatus


def _payload(symbol: str = "PETR4") -> bytes:
    return json.dumps(
        {
            "results": [
                {
                    "requestedSymbol": symbol,
                    "symbol": symbol,
                    "changed": False,
                    "data": {
                        "currency": "BRL",
                        "regularMarketPrice": 41.18,
                        "regularMarketChange": -0.58,
                        "regularMarketChangePercent": -1.39,
                        "regularMarketVolume": 34024700,
                        "regularMarketDayLow": 40.8,
                        "regularMarketDayHigh": 42.1,
                        "regularMarketTime": "2026-10-13T15:00:00.000Z",
                    },
                }
            ],
            "requestedAt": "2026-10-13T15:00:05.000Z",
            "took": 25,
        }
    ).encode("utf-8")


def test_brapi_snapshot_uses_header_token_and_normalizes_quote(monkeypatch):
    observed = {}

    def fake_download(url, policy=None, *, retry_policy=None, headers=None, payload_validator=None):
        observed["url"] = url
        observed["headers"] = dict(headers or {})
        observed["hosts"] = policy.allowed_hosts
        return _payload()

    monkeypatch.setattr("mercado_financeiro.data.brapi.download_https_with_retry", fake_download)

    provider = BrapiMarketDataProvider(
        api_key="secret-token",
        now_fn=lambda: datetime(2026, 10, 13, 15, 0, 10, tzinfo=timezone.utc),
    )
    provider.connect()
    events = provider.snapshot(["PETR4"])

    assert observed["url"].endswith("symbols=PETR4")
    assert observed["headers"]["Authorization"] == "Bearer secret-token"
    assert observed["hosts"] == frozenset({"brapi.dev"})
    assert events[0].instrument == "PETR4"
    assert events[0].payload["price"] == 41.18
    assert events[0].payload["market_data_class"] == "delayed_polling"
    assert len(events[0].payload["source_sha256"]) == 64
    assert provider.health().status is FeedStatus.HEALTHY


def test_brapi_sandbox_does_not_send_authorization_header(monkeypatch):
    observed = {}

    def fake_download(url, policy=None, *, retry_policy=None, headers=None, payload_validator=None):
        observed["headers"] = dict(headers or {})
        return _payload("VALE3")

    monkeypatch.setattr("mercado_financeiro.data.brapi.download_https_with_retry", fake_download)

    provider = BrapiMarketDataProvider(
        now_fn=lambda: datetime(2026, 10, 13, 15, 0, 10, tzinfo=timezone.utc),
    )
    provider.connect()
    event = provider.snapshot(["VALE3"])[0]
    assert "Authorization" not in observed["headers"]
    assert event.instrument == "VALE3"


def test_brapi_rejects_symbol_mismatch(monkeypatch):
    monkeypatch.setattr(
        "mercado_financeiro.data.brapi.download_https_with_retry",
        lambda *args, **kwargs: _payload("VALE3"),
    )
    provider = BrapiMarketDataProvider(
        now_fn=lambda: datetime(2026, 10, 13, 15, 0, 10, tzinfo=timezone.utc),
    )
    provider.connect()
    with pytest.raises(ValueError, match="symbol mismatch"):
        provider.snapshot(["PETR4"])


def test_brapi_is_explicitly_polling_only():
    provider = BrapiMarketDataProvider()
    provider.connect()
    with pytest.raises(RuntimeError, match="polling provider"):
        next(provider.subscribe(["PETR4"]))

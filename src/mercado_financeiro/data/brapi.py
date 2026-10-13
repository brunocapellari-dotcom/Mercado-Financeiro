from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable, Iterable, Iterator
from urllib.parse import urlencode

from mercado_financeiro.security import (
    DownloadPolicy,
    RetryPolicy,
    download_https_with_retry,
)

from .provider import FeedHealth, FeedStatus, MarketDataEvent, MarketDataProvider


class BrapiMarketDataProvider(MarketDataProvider):
    """Delayed B3 quote provider backed by brapi.dev REST v2.

    The provider is polling-only. It deliberately does not emulate a streaming feed.
    One symbol is requested at a time so the free plan's one-asset request contract is
    respected. The optional token is sent only in the Authorization header.

    This adapter is suitable for PAPER/SHADOW and analytics. It is not a LIVE broker
    execution feed and must never be promoted as one.
    """

    name = "BRAPI"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 2_000_000,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._policy = DownloadPolicy(
            allowed_hosts=frozenset({"brapi.dev"}),
            timeout_seconds=timeout_seconds,
            max_bytes=max_response_bytes,
        )
        self._retry = RetryPolicy(
            attempts=4,
            initial_delay_seconds=1.0,
            max_delay_seconds=8.0,
            retry_http_statuses=frozenset({408, 425, 429, 500, 502, 503, 504}),
        )
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._connected = False
        self._last_event: MarketDataEvent | None = None
        self._last_error: str | None = None

    def connect(self) -> None:
        self._connected = True
        self._last_error = None

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, instruments: Iterable[str]) -> Iterator[MarketDataEvent]:
        raise RuntimeError(
            "BRAPI is a delayed polling provider; use snapshot() instead of streaming subscribe()"
        )
        yield from ()

    def snapshot(self, instruments: Iterable[str]) -> list[MarketDataEvent]:
        if not self._connected:
            raise RuntimeError("BRAPI provider must be connected before snapshot")

        symbols = tuple(dict.fromkeys(self._normalize_symbol(value) for value in instruments))
        if not symbols:
            raise ValueError("at least one instrument is required")

        events: list[MarketDataEvent] = []
        try:
            for symbol in symbols:
                events.append(self._fetch_symbol(symbol))
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise

        self._last_error = None
        self._last_event = events[-1]
        return events

    def health(self) -> FeedHealth:
        now = self._utc_now()
        if not self._connected:
            return FeedHealth.disconnected(self.name, self._last_error)
        if self._last_error is not None:
            return FeedHealth(
                provider=self.name,
                status=FeedStatus.DISCONNECTED,
                checked_at=now,
                details=self._last_error,
            )
        if self._last_event is None:
            return FeedHealth(
                provider=self.name,
                status=FeedStatus.STALE,
                checked_at=now,
                details="connected but no quote snapshot has been collected",
            )
        return FeedHealth(
            provider=self.name,
            status=FeedStatus.HEALTHY,
            checked_at=now,
            last_exchange_timestamp=self._last_event.exchange_timestamp,
            last_received_timestamp=self._last_event.received_timestamp,
            details="delayed polling market data; not a live execution feed",
        )

    def _fetch_symbol(self, symbol: str) -> MarketDataEvent:
        query = urlencode({"symbols": symbol})
        url = f"https://brapi.dev/api/v2/stocks/quote?{query}"
        headers = {"Accept": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = download_https_with_retry(
            url,
            self._policy,
            retry_policy=self._retry,
            headers=headers,
        )
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("BRAPI returned invalid JSON") from exc

        results = decoded.get("results")
        if not isinstance(results, list) or len(results) != 1:
            raise ValueError("BRAPI quote response must contain exactly one result")
        item = results[0]
        if not isinstance(item, dict):
            raise ValueError("BRAPI quote result must be an object")
        data = item.get("data")
        if not isinstance(data, dict):
            raise ValueError("BRAPI quote result has no data object")

        returned_symbol = str(item.get("symbol") or item.get("requestedSymbol") or "").upper()
        if returned_symbol != symbol:
            raise ValueError(
                f"BRAPI symbol mismatch: requested={symbol!r} returned={returned_symbol!r}"
            )

        raw_price = data.get("regularMarketPrice")
        if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
            raise ValueError("BRAPI quote has invalid regularMarketPrice")
        price = float(raw_price)
        if price <= 0:
            raise ValueError("BRAPI quote price must be positive")

        raw_time = data.get("regularMarketTime")
        if not isinstance(raw_time, str) or not raw_time.strip():
            raise ValueError("BRAPI quote has no regularMarketTime")
        exchange_timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if exchange_timestamp.tzinfo is None or exchange_timestamp.utcoffset() is None:
            raise ValueError("BRAPI regularMarketTime must be timezone-aware")
        exchange_timestamp = exchange_timestamp.astimezone(timezone.utc)

        received_at = self._utc_now()
        if received_at < exchange_timestamp:
            raise ValueError("BRAPI quote timestamp is in the future")

        requested_at = decoded.get("requestedAt")
        normalized_payload = {
            "symbol": symbol,
            "price": price,
            "currency": data.get("currency"),
            "volume": data.get("regularMarketVolume"),
            "change": data.get("regularMarketChange"),
            "change_percent": data.get("regularMarketChangePercent"),
            "day_low": data.get("regularMarketDayLow"),
            "day_high": data.get("regularMarketDayHigh"),
            "requested_at": requested_at,
            "source_sha256": sha256(payload).hexdigest(),
            "source": "BRAPI_V2_STOCKS_QUOTE",
            "market_data_class": "delayed_polling",
        }
        return MarketDataEvent(
            provider=self.name,
            instrument=symbol,
            event_type="quote",
            exchange_timestamp=exchange_timestamp,
            received_timestamp=received_at,
            sequence=None,
            payload=normalized_payload,
        )

    def _utc_now(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_symbol(value: str) -> str:
        symbol = str(value).strip().upper()
        if not symbol:
            raise ValueError("instrument symbol cannot be empty")
        if not symbol.replace("^", "").replace(".", "").isalnum():
            raise ValueError(f"invalid market-data symbol: {value!r}")
        if len(symbol) > 20:
            raise ValueError("market-data symbol is too long")
        return symbol

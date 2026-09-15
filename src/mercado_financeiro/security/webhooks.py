from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
from hashlib import sha256

from .replay import InMemoryReplayStore, ReplayStore


class WebhookVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedWebhook:
    event_id: str
    timestamp: int
    payload: bytes


class HMACWebhookVerifier:
    """Generic HMAC-SHA256 verifier with timestamp and atomic replay protection.

    Vendors with a different documented signature scheme should implement a
    separate verifier rather than weakening this one. The default replay store
    is process-local and therefore paper/test only; live must inject a durable
    atomic store shared across replicas.
    """

    def __init__(
        self,
        secret: bytes,
        *,
        max_age_seconds: int = 300,
        replay_store: ReplayStore | None = None,
    ) -> None:
        if not secret:
            raise ValueError("webhook secret is required")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._secret = secret
        self._max_age_seconds = max_age_seconds
        self._replay_store = replay_store or InMemoryReplayStore()

    @property
    def replay_store_live_safe(self) -> bool:
        return bool(getattr(self._replay_store, "live_safe", False))

    def verify(
        self,
        *,
        payload: bytes,
        signature_hex: str,
        timestamp: int,
        event_id: str,
        now: datetime | None = None,
    ) -> VerifiedWebhook:
        if not event_id.strip():
            raise WebhookVerificationError("missing event_id")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        current = current.astimezone(timezone.utc)
        age = abs(current.timestamp() - timestamp)
        if age > self._max_age_seconds:
            raise WebhookVerificationError("stale webhook timestamp")

        signed = str(timestamp).encode("ascii") + b"." + payload
        expected = hmac.new(self._secret, signed, sha256).hexdigest()
        if not hmac.compare_digest(expected, signature_hex.strip().lower()):
            raise WebhookVerificationError("invalid webhook signature")

        expiry = current + timedelta(seconds=self._max_age_seconds)
        if not self._replay_store.mark_if_new(event_id, expires_at=expiry, now=current):
            raise WebhookVerificationError("webhook replay detected")
        return VerifiedWebhook(event_id=event_id, timestamp=timestamp, payload=payload)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from hashlib import sha256


class WebhookVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedWebhook:
    event_id: str
    timestamp: int
    payload: bytes


class HMACWebhookVerifier:
    """Generic HMAC-SHA256 verifier with timestamp and replay protection.

    Vendors with a different documented signature scheme should implement a
    separate verifier rather than weakening this one.
    """

    def __init__(self, secret: bytes, *, max_age_seconds: int = 300) -> None:
        if not secret:
            raise ValueError("webhook secret is required")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._secret = secret
        self._max_age_seconds = max_age_seconds
        self._seen_event_ids: set[str] = set()

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
        age = abs(current.timestamp() - timestamp)
        if age > self._max_age_seconds:
            raise WebhookVerificationError("stale webhook timestamp")
        if event_id in self._seen_event_ids:
            raise WebhookVerificationError("webhook replay detected")

        signed = str(timestamp).encode("ascii") + b"." + payload
        expected = hmac.new(self._secret, signed, sha256).hexdigest()
        if not hmac.compare_digest(expected, signature_hex.strip().lower()):
            raise WebhookVerificationError("invalid webhook signature")

        self._seen_event_ids.add(event_id)
        return VerifiedWebhook(event_id=event_id, timestamp=timestamp, payload=payload)

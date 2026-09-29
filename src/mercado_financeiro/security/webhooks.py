from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
from hashlib import sha256
import string

from .replay import InMemoryReplayStore, ReplayStore


class WebhookVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedWebhook:
    event_id: str
    timestamp: int
    payload: bytes


class HMACWebhookVerifier:
    """Bounded HMAC-SHA256 verifier with atomic replay protection."""

    def __init__(
        self,
        secret: bytes,
        *,
        max_age_seconds: int = 300,
        max_payload_bytes: int = 1_048_576,
        max_event_id_bytes: int = 256,
        replay_store: ReplayStore | None = None,
    ) -> None:
        if not isinstance(secret, bytes) or not secret:
            raise ValueError("webhook secret must be non-empty bytes")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        if max_payload_bytes <= 0 or max_event_id_bytes <= 0:
            raise ValueError("webhook size limits must be positive")
        self._secret = secret
        self._max_age_seconds = max_age_seconds
        self._max_payload_bytes = max_payload_bytes
        self._max_event_id_bytes = max_event_id_bytes
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
        if not isinstance(payload, bytes):
            raise WebhookVerificationError("payload must be bytes")
        if len(payload) > self._max_payload_bytes:
            raise WebhookVerificationError("webhook payload exceeds configured limit")

        normalized_event_id = str(event_id).strip()
        if not normalized_event_id:
            raise WebhookVerificationError("missing event_id")
        if len(normalized_event_id.encode("utf-8")) > self._max_event_id_bytes:
            raise WebhookVerificationError("event_id exceeds configured limit")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized_event_id):
            raise WebhookVerificationError("event_id contains control characters")

        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise WebhookVerificationError("invalid webhook timestamp")
        signature = str(signature_hex).strip().lower()
        if len(signature) != 64 or any(ch not in string.hexdigits.lower() for ch in signature):
            raise WebhookVerificationError("invalid webhook signature encoding")

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        current = current.astimezone(timezone.utc)
        age = current.timestamp() - timestamp
        if age > self._max_age_seconds:
            raise WebhookVerificationError("stale webhook timestamp")
        if age < -self._max_age_seconds:
            raise WebhookVerificationError("webhook timestamp too far in the future")

        signed = str(timestamp).encode("ascii") + b"." + payload
        expected = hmac.new(self._secret, signed, sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError("invalid webhook signature")

        expiry = current + timedelta(seconds=self._max_age_seconds)
        if not self._replay_store.mark_if_new(
            normalized_event_id, expires_at=expiry, now=current
        ):
            raise WebhookVerificationError("webhook replay detected")
        return VerifiedWebhook(
            event_id=normalized_event_id,
            timestamp=timestamp,
            payload=payload,
        )

from datetime import datetime, timezone
from hashlib import sha256
import hmac

import pytest

from mercado_financeiro.architecture import (
    LiveCapabilities,
    assert_live_runtime,
    evaluate_live_runtime,
)
from mercado_financeiro.audit import AuditLedger
from mercado_financeiro.execution import InMemoryIdempotencyStore
from mercado_financeiro.security import HMACWebhookVerifier, InMemoryReplayStore


def test_live_runtime_fails_closed_by_default():
    result = evaluate_live_runtime(LiveCapabilities())
    assert not result.approved
    assert "durable_idempotency" in result.missing
    assert "secret_manager" in result.missing
    assert "independent_kill_switch" in result.missing
    with pytest.raises(RuntimeError):
        assert_live_runtime(LiveCapabilities())


def test_live_runtime_only_passes_when_every_hardening_capability_is_true():
    result = evaluate_live_runtime(
        LiveCapabilities(
            durable_idempotency=True,
            durable_webhook_replay_protection=True,
            external_immutable_audit_log=True,
            secret_manager=True,
            restricted_egress=True,
            independent_reconciliation=True,
            independent_kill_switch=True,
            separate_live_identity=True,
            broker_mfa=True,
            ip_restriction_enforced_or_unsupported=True,
        )
    )
    assert result.approved
    assert result.missing == ()


def test_reference_stores_are_explicitly_not_live_safe():
    assert InMemoryIdempotencyStore.live_safe is False
    assert InMemoryReplayStore.live_safe is False
    assert AuditLedger.live_safe is False


def test_webhook_replay_store_remains_atomic_contract():
    secret = b"test-secret"
    payload = b"{}"
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    signature = hmac.new(
        secret,
        str(timestamp).encode("ascii") + b"." + payload,
        sha256,
    ).hexdigest()
    verifier = HMACWebhookVerifier(secret)
    assert verifier.replay_store_live_safe is False
    verifier.verify(
        payload=payload,
        signature_hex=signature,
        timestamp=timestamp,
        event_id="evt-live-gate",
        now=now,
    )
    with pytest.raises(ValueError, match="replay"):
        verifier.verify(
            payload=payload,
            signature_hex=signature,
            timestamp=timestamp,
            event_id="evt-live-gate",
            now=now,
        )

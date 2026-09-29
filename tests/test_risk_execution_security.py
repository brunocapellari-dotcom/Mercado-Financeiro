from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import hmac

import pytest

from mercado_financeiro.execution import (
    BrokerOrderAck,
    DeterministicExecutionEngine,
    IdempotencyConflict,
)
from mercado_financeiro.risk import (
    DeterministicRiskEngine,
    OrderIntent,
    RiskContext,
    RiskLimits,
)
from mercado_financeiro.security import (
    HMACWebhookVerifier,
    SourceSecurityError,
    WebhookVerificationError,
    validate_source_url,
)


class FakeBroker:
    def __init__(self) -> None:
        self.calls = 0
        self.client_order_ids: list[str] = []

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        self.calls += 1
        self.client_order_ids.append(client_order_id)
        return BrokerOrderAck(accepted=True, broker_order_id=f"B-{self.calls}", status="accepted")


def _limits() -> RiskLimits:
    return RiskLimits(
        max_order_notional=Decimal("100000"),
        max_abs_position=Decimal("10000"),
        allowed_instruments=frozenset({"PETR4"}),
        trading_start=time(10, 0),
        trading_end=time(18, 0),
        max_drawdown_fraction=Decimal("0.10"),
        max_daily_loss=Decimal("1000"),
        max_adv_participation=Decimal("0.10"),
        max_market_data_age_seconds=Decimal("3"),
    )


def _order(*, price: str = "10", key: str = "order-1") -> OrderIntent:
    return OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal(price),
        signal_id="signal-1",
        idempotency_key=key,
        created_at=datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
    )


def _context(**overrides) -> RiskContext:
    values = {
        "current_position": Decimal("0"),
        "equity": Decimal("100000"),
        "peak_equity": Decimal("100000"),
        "pnl_today": Decimal("0"),
        "adv_notional": Decimal("1000000"),
        "market_data_age_seconds": Decimal("1"),
        "now": datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc),
        "kill_switch_engaged": False,
    }
    values.update(overrides)
    return RiskContext(**values)


def test_risk_engine_approves_valid_order_and_blocks_stale_feed():
    engine = DeterministicRiskEngine(_limits())
    assert engine.evaluate(_order(), _context()).approved is True

    stale = engine.evaluate(
        _order(),
        _context(market_data_age_seconds=Decimal("10")),
    )
    assert stale.approved is False
    assert "stale_market_data" in stale.reasons


def test_risk_engine_blocks_kill_switch_limits_hours_and_liquidity():
    engine = DeterministicRiskEngine(_limits())

    killed = engine.evaluate(_order(), _context(kill_switch_engaged=True))
    assert "kill_switch_engaged" in killed.reasons

    outside = engine.evaluate(
        _order(),
        _context(now=datetime(2026, 9, 15, 23, 0, tzinfo=timezone.utc)),
    )
    assert "outside_trading_hours" in outside.reasons

    illiquid = engine.evaluate(_order(), _context(adv_notional=Decimal("5000")))
    assert "liquidity_limit_exceeded" in illiquid.reasons


def test_execution_never_submits_risk_rejected_order():
    broker = FakeBroker()
    engine = DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(_limits()),
        broker=broker,
    )
    result = engine.execute(
        _order(),
        _context(kill_switch_engaged=True),
    )
    assert result.accepted is False
    assert result.status == "risk_rejected"
    assert broker.calls == 0


def test_order_duplication_is_idempotent():
    broker = FakeBroker()
    engine = DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(_limits()),
        broker=broker,
    )
    first = engine.execute(_order(), _context())
    second = engine.execute(_order(), _context())

    assert first.accepted is True
    assert second.accepted is True
    assert second.duplicate is True
    assert first.client_order_id == second.client_order_id
    assert broker.calls == 1


def test_idempotency_key_reuse_with_different_payload_fails_closed():
    broker = FakeBroker()
    engine = DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(_limits()),
        broker=broker,
    )
    engine.execute(_order(price="10", key="same-key"), _context())
    with pytest.raises(IdempotencyConflict):
        engine.execute(_order(price="11", key="same-key"), _context())
    assert broker.calls == 1


def test_concurrent_duplicate_order_submits_once():
    broker = FakeBroker()
    engine = DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(_limits()),
        broker=broker,
    )
    order = _order(key="race-key")
    context = _context()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: engine.execute(order, context), range(8)))

    assert broker.calls == 1
    assert sum(1 for result in results if not result.duplicate) == 1
    assert sum(1 for result in results if result.duplicate) == 7


def test_api_spoofing_and_embedded_credentials_are_rejected():
    with pytest.raises(SourceSecurityError):
        validate_source_url("https://evil.example/b3/file.zip")
    with pytest.raises(SourceSecurityError):
        validate_source_url("https://user:password@www.b3.com.br/file.zip")
    with pytest.raises(SourceSecurityError):
        validate_source_url("http://www.b3.com.br/file.zip")


def test_webhook_signature_spoof_replay_and_stale_are_rejected():
    secret = b"unit-test-secret"
    payload = b'{"event":"fill","id":"123"}'
    now = datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    signed = str(timestamp).encode("ascii") + b"." + payload
    signature = hmac.new(secret, signed, sha256).hexdigest()

    verifier = HMACWebhookVerifier(secret, max_age_seconds=300)
    verified = verifier.verify(
        payload=payload,
        signature_hex=signature,
        timestamp=timestamp,
        event_id="evt-1",
        now=now,
    )
    assert verified.event_id == "evt-1"

    with pytest.raises(WebhookVerificationError, match="replay"):
        verifier.verify(
            payload=payload,
            signature_hex=signature,
            timestamp=timestamp,
            event_id="evt-1",
            now=now,
        )

    spoof_verifier = HMACWebhookVerifier(secret, max_age_seconds=300)
    with pytest.raises(WebhookVerificationError, match="signature"):
        spoof_verifier.verify(
            payload=payload,
            signature_hex="00" * 32,
            timestamp=timestamp,
            event_id="evt-2",
            now=now,
        )

    stale_verifier = HMACWebhookVerifier(secret, max_age_seconds=300)
    with pytest.raises(WebhookVerificationError, match="stale"):
        stale_verifier.verify(
            payload=payload,
            signature_hex=signature,
            timestamp=timestamp,
            event_id="evt-3",
            now=now + timedelta(minutes=10),
        )


def test_webhook_limits_and_signature_encoding_fail_closed():
    verifier = HMACWebhookVerifier(
        b"unit-test-secret",
        max_payload_bytes=8,
        max_event_id_bytes=8,
    )
    now = datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)
    with pytest.raises(WebhookVerificationError, match="payload"):
        verifier.verify(
            payload=b"x" * 9,
            signature_hex="00" * 32,
            timestamp=int(now.timestamp()),
            event_id="evt",
            now=now,
        )
    with pytest.raises(WebhookVerificationError, match="event_id"):
        verifier.verify(
            payload=b"{}",
            signature_hex="00" * 32,
            timestamp=int(now.timestamp()),
            event_id="event-too-long",
            now=now,
        )
    with pytest.raises(WebhookVerificationError, match="encoding"):
        verifier.verify(
            payload=b"{}",
            signature_hex="not-hex",
            timestamp=int(now.timestamp()),
            event_id="evt",
            now=now,
        )


def test_broker_rejection_ack_is_not_misclassified_as_accepted():
    class RejectingBroker:
        def submit_order(self, order, *, client_order_id):
            return BrokerOrderAck(
                accepted=False,
                status="rejected",
                broker_order_id="R-1",
            )

    engine = DeterministicExecutionEngine(
        risk_engine=DeterministicRiskEngine(_limits()),
        broker=RejectingBroker(),
    )
    result = engine.execute(_order(key="reject-ack"), _context())
    assert result.accepted is False
    assert result.status == "rejected"

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mercado_financeiro.architecture import AIRole
from mercado_financeiro.forecast import Forecast
from mercado_financeiro.intelligence import IntelligenceArtifact
from mercado_financeiro.reconciliation import DeterministicReconciler
from mercado_financeiro.signal import SignalDirection, SignalProposal


def test_intelligence_forecast_signal_contracts_are_time_bounded():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    artifact = IntelligenceArtifact(
        role=AIRole.MACRO,
        artifact_id="intel-1",
        generated_at=now,
        as_of=now - timedelta(minutes=1),
        summary="macro state",
        evidence_ids=("bcb:selic",),
        confidence=0.7,
    )
    assert artifact.role is AIRole.MACRO

    forecast = Forecast(
        forecast_id="fc-1",
        model_id="m1",
        model_version="1.0",
        instrument="PETR4",
        target="return_1d",
        value=0.01,
        generated_at=now,
        valid_until=now + timedelta(days=1),
        horizon_seconds=86400,
        source_artifact_ids=(artifact.artifact_id,),
    )
    signal = SignalProposal(
        signal_id="sig-1",
        strategy_id="s1",
        instrument="PETR4",
        direction=SignalDirection.LONG,
        strength=0.6,
        generated_at=now,
        expires_at=now + timedelta(hours=4),
        forecast_ids=(forecast.forecast_id,),
    )
    assert signal.forecast_ids == ("fc-1",)

    with pytest.raises(ValueError):
        Forecast(
            forecast_id="bad",
            model_id="m",
            model_version="1",
            instrument="PETR4",
            target="return",
            value=0,
            generated_at=now,
            valid_until=now,
            horizon_seconds=1,
        )


def test_reconciliation_fails_closed_on_position_or_cash_mismatch():
    reconciler = DeterministicReconciler()
    ok = reconciler.reconcile(
        internal_positions={"PETR4": Decimal("100")},
        broker_positions={"PETR4": Decimal("100")},
        internal_cash=Decimal("1000.00"),
        broker_cash=Decimal("1000.00"),
    )
    assert ok.approved is True

    bad = reconciler.reconcile(
        internal_positions={"PETR4": Decimal("100")},
        broker_positions={"PETR4": Decimal("99")},
        internal_cash=Decimal("1000.00"),
        broker_cash=Decimal("999.50"),
    )
    assert bad.approved is False
    assert bad.position_mismatches[0].key == "PETR4"
    assert bad.cash_mismatch is not None

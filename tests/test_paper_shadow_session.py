from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from mercado_financeiro.execution.brokerage import (
    BrokerageCostSchedule,
    DeterministicBrokerageModel,
    MarketExecutionState,
)
from mercado_financeiro.paper.dashboard import render_dashboard_html, snapshot_payload
from mercado_financeiro.paper.session import PaperShadowSession
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskContext, RiskLimits
from mercado_financeiro.runtime import RuntimeMode


def _risk() -> DeterministicRiskEngine:
    return DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=Decimal("100000"),
            max_abs_position=Decimal("10000"),
            allowed_instruments=frozenset({"PETR4"}),
            trading_start=time(10, 0),
            trading_end=time(18, 0),
            max_daily_loss=Decimal("1000"),
        )
    )


def _market() -> MarketExecutionState:
    return MarketExecutionState(
        timestamp=datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc),
        bid=Decimal("30.00"),
        ask=Decimal("30.10"),
        available_quantity=Decimal("10000"),
        adv_notional=Decimal("10000000"),
    )


def _context(*, killed: bool = False) -> RiskContext:
    return RiskContext(
        current_position=Decimal("999999"),
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        pnl_today=Decimal("0"),
        adv_notional=Decimal("10000000"),
        market_data_age_seconds=Decimal("1"),
        now=datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc),
        kill_switch_engaged=killed,
    )


def _order(key: str = "paper-1") -> OrderIntent:
    return OrderIntent(
        instrument="PETR4",
        side="buy",
        quantity=Decimal("100"),
        price=Decimal("30.10"),
        signal_id="signal-alpha",
        idempotency_key=key,
        created_at=datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc),
    )


def _session(mode: RuntimeMode = RuntimeMode.PAPER) -> PaperShadowSession:
    return PaperShadowSession(
        mode=mode,
        risk_engine=_risk(),
        brokerage=DeterministicBrokerageModel(
            BrokerageCostSchedule(
                fee_bps=Decimal("1"),
                base_slippage_bps=Decimal("2"),
                settlement_business_days=0,
            )
        ),
        initial_cash=Decimal("100000"),
    )


def test_paper_session_risk_fill_accounting_and_dashboard() -> None:
    session = _session()
    row = session.process_order(_order(), risk_context=_context(), market=_market())
    assert row.status == "filled"
    assert row.fill_price is not None
    assert row.fee > 0

    snapshot = session.snapshot(marks={"PETR4": Decimal("31")})
    assert snapshot.orders == 1
    assert snapshot.fills == 1
    assert snapshot.positions["PETR4"] == Decimal("100")
    assert snapshot.equity is not None
    assert snapshot_payload(snapshot)["mode"] == "paper"
    html = render_dashboard_html(snapshot)
    assert "Mercado Financeiro" in html
    assert "PETR4" in html
    assert "signal-alpha" in html


def test_paper_session_is_exactly_once_and_uses_ledger_position_for_risk() -> None:
    session = _session()
    first = session.process_order(_order(), risk_context=_context(), market=_market())
    duplicate = session.process_order(_order(), risk_context=_context(), market=_market())
    assert first.status == "filled"
    assert duplicate.duplicate is True
    snapshot = session.snapshot(marks={"PETR4": Decimal("31")})
    assert snapshot.positions["PETR4"] == Decimal("100")
    assert snapshot.orders == 1
    assert snapshot.duplicates == 1


def test_paper_session_fail_closed_on_risk_rejection() -> None:
    session = _session(RuntimeMode.SHADOW)
    row = session.process_order(_order(), risk_context=_context(killed=True), market=_market())
    assert row.status == "risk_rejected"
    assert "kill_switch_engaged" in row.risk_reasons
    snapshot = session.snapshot()
    assert snapshot.fills == 0
    assert snapshot.rejected == 1


def test_paper_session_refuses_live_mode() -> None:
    with pytest.raises(ValueError, match="PAPER or SHADOW"):
        _session(RuntimeMode.LIVE)


class _PartialFillBrokerage(DeterministicBrokerageModel):
    """Simulated broker that fills only part of the order (no live boundary)."""

    def simulate_market_order(self, order, market, *, cash_available):  # type: ignore[override]
        from dataclasses import replace as _replace

        full = super().simulate_market_order(order, market, cash_available=cash_available)
        return _replace(full, quantity=order.quantity / 2)


def test_paper_session_books_only_the_filled_quantity() -> None:
    session = PaperShadowSession(
        mode=RuntimeMode.PAPER,
        risk_engine=_risk(),
        brokerage=_PartialFillBrokerage(
            BrokerageCostSchedule(
                fee_bps=Decimal("1"),
                base_slippage_bps=Decimal("2"),
                settlement_business_days=0,
            )
        ),
        initial_cash=Decimal("100000"),
    )
    row = session.process_order(_order(), risk_context=_context(), market=_market())
    assert row.status == "filled"
    assert row.quantity == Decimal("50")
    snapshot = session.snapshot(marks={"PETR4": Decimal("31")})
    assert snapshot.positions["PETR4"] == Decimal("50")

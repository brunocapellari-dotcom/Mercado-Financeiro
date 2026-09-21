from decimal import Decimal

import pytest

from mercado_financeiro.accounting import DuplicateFillError, PortfolioAccountingLedger


def test_accounting_ledger_tracks_average_cost_cash_and_realized_pnl():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("10000"))
    ledger.apply_fill(
        fill_id="f1",
        instrument="PETR4",
        signed_quantity=Decimal("100"),
        price=Decimal("20"),
        fee=Decimal("2"),
    )
    position = ledger.apply_fill(
        fill_id="f2",
        instrument="PETR4",
        signed_quantity=Decimal("100"),
        price=Decimal("22"),
        fee=Decimal("2"),
    )
    assert position.quantity == Decimal("200")
    assert position.average_price == Decimal("21")

    position = ledger.apply_fill(
        fill_id="f3",
        instrument="PETR4",
        signed_quantity=Decimal("-50"),
        price=Decimal("25"),
        fee=Decimal("1"),
    )
    assert position.quantity == Decimal("150")
    assert position.average_price == Decimal("21")
    assert position.realized_pnl == Decimal("200")

    snapshot = ledger.snapshot()
    assert snapshot.cash == Decimal("7045")
    assert snapshot.cumulative_fees == Decimal("5")
    assert snapshot.realized_pnl == Decimal("200")


def test_accounting_crosses_through_flat_at_new_fill_price():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("1000"))
    ledger.apply_fill(
        fill_id="a",
        instrument="TEST3",
        signed_quantity=Decimal("10"),
        price=Decimal("10"),
    )
    position = ledger.apply_fill(
        fill_id="b",
        instrument="TEST3",
        signed_quantity=Decimal("-15"),
        price=Decimal("12"),
    )
    assert position.quantity == Decimal("-5")
    assert position.average_price == Decimal("12")
    assert position.realized_pnl == Decimal("20")


def test_accounting_fill_ids_are_exactly_once():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("1000"))
    ledger.apply_fill(
        fill_id="once",
        instrument="PETR4",
        signed_quantity=Decimal("1"),
        price=Decimal("30"),
    )
    with pytest.raises(DuplicateFillError, match="duplicate fill_id"):
        ledger.apply_fill(
            fill_id="once",
            instrument="PETR4",
            signed_quantity=Decimal("1"),
            price=Decimal("30"),
        )


def test_mark_to_market_requires_every_open_position_mark():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("1000"))
    ledger.apply_fill(
        fill_id="f",
        instrument="PETR4",
        signed_quantity=Decimal("10"),
        price=Decimal("20"),
    )
    marked = ledger.mark_to_market({"PETR4": Decimal("25")})
    assert marked.market_value == Decimal("250")
    assert marked.equity == Decimal("1050")
    assert marked.unrealized_pnl == Decimal("50")
    assert marked.gross_exposure == Decimal("250")

    with pytest.raises(ValueError, match="missing marks"):
        ledger.mark_to_market({})


def test_realized_pnl_survives_full_position_close():
    ledger = PortfolioAccountingLedger(initial_cash=Decimal("1000"))
    ledger.apply_fill(
        fill_id="open",
        instrument="TEST3",
        signed_quantity=Decimal("10"),
        price=Decimal("10"),
    )
    ledger.apply_fill(
        fill_id="close",
        instrument="TEST3",
        signed_quantity=Decimal("-10"),
        price=Decimal("12"),
    )
    snapshot = ledger.snapshot()
    assert snapshot.positions == {}
    assert snapshot.realized_pnl == Decimal("20")

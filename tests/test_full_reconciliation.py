from decimal import Decimal

from mercado_financeiro.reconciliation import (
    DeterministicFullReconciler,
    ExecutionLedgerSnapshot,
    FillRecord,
)


def _snapshot(*, cash="1000", fees="5", pnl="20", order_status="accepted", fill_price="10"):
    fill = FillRecord(
        fill_id="fill-1",
        instrument="PETR4",
        quantity=Decimal("100"),
        price=Decimal(fill_price),
        fee=Decimal("2"),
    )
    return ExecutionLedgerSnapshot(
        positions={"PETR4": Decimal("100")},
        cash=Decimal(cash),
        cumulative_fees=Decimal(fees),
        realized_pnl=Decimal(pnl),
        open_orders={"mf-1": order_status},
        fills={"fill-1": fill},
    )


def test_full_reconciliation_approves_identical_ledgers():
    result = DeterministicFullReconciler().reconcile(
        internal=_snapshot(),
        broker=_snapshot(),
    )
    assert result.approved
    assert not result.order_mismatches
    assert not result.fill_mismatches


def test_full_reconciliation_fails_on_fees_orders_and_fills():
    result = DeterministicFullReconciler().reconcile(
        internal=_snapshot(),
        broker=_snapshot(fees="6", order_status="partially_filled", fill_price="10.10"),
    )
    assert not result.approved
    assert result.fee_mismatch is not None
    assert result.order_mismatches
    assert "fill-1:price" in result.fill_mismatches

from datetime import date
from decimal import Decimal

from mercado_financeiro.accounting.tax import (
    BrazilTaxRuleSet,
    TaxPeriodInput,
    calculate_brazil_tax_accrual,
)


def _rules() -> BrazilTaxRuleSet:
    return BrazilTaxRuleSet(
        rule_id="test-only",
        category="cash-equity-swing",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        realized_gain_rate=Decimal("0.15"),
        transaction_tax_bps=Decimal("0.5"),
        source_reference="official-rule-placeholder-for-test",
    )


def test_tax_accrual_offsets_losses_and_keeps_transaction_tax_separate():
    result = calculate_brazil_tax_accrual(
        TaxPeriodInput(
            period_end=date(2026, 9, 30),
            realized_pnl=Decimal("1000"),
            sale_notional=Decimal("50000"),
            opening_loss_carryforward=Decimal("200"),
        ),
        _rules(),
    )
    assert result.taxable_gain == Decimal("800")
    assert result.income_tax == Decimal("120.00")
    assert result.transaction_tax == Decimal("2.5")
    assert result.ending_loss_carryforward == Decimal("0")

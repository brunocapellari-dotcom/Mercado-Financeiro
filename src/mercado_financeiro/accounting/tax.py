from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class BrazilTaxRuleSet:
    """Versioned, externally-audited tax parameters.

    No statutory rate is hard-coded here. A rule set is valid only when its
    source_reference and effective dates have been reviewed against an official
    Receita/legislative source for the applicable investor and transaction type.
    """

    rule_id: str
    category: str
    effective_from: date
    effective_to: date | None
    realized_gain_rate: Decimal
    transaction_tax_bps: Decimal
    source_reference: str
    loss_offset_allowed: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.category.strip() or not self.source_reference.strip():
            raise ValueError("rule_id/category/source_reference are required")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("tax effective interval is invalid")
        if self.realized_gain_rate < 0 or self.realized_gain_rate > 1:
            raise ValueError("realized_gain_rate must be in [0,1]")
        if self.transaction_tax_bps < 0:
            raise ValueError("transaction_tax_bps cannot be negative")


@dataclass(frozen=True)
class TaxPeriodInput:
    period_end: date
    realized_pnl: Decimal
    sale_notional: Decimal
    opening_loss_carryforward: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.sale_notional < 0 or self.opening_loss_carryforward < 0:
            raise ValueError("sale_notional/loss carryforward cannot be negative")


@dataclass(frozen=True)
class TaxAccrual:
    taxable_gain: Decimal
    income_tax: Decimal
    transaction_tax: Decimal
    ending_loss_carryforward: Decimal
    rule_id: str


def calculate_brazil_tax_accrual(
    period: TaxPeriodInput,
    rules: BrazilTaxRuleSet,
) -> TaxAccrual:
    if period.period_end < rules.effective_from:
        raise ValueError("tax rule is not yet effective")
    if rules.effective_to is not None and period.period_end > rules.effective_to:
        raise ValueError("tax rule is expired")

    pnl = period.realized_pnl
    carry = period.opening_loss_carryforward
    if pnl < 0:
        ending_loss = carry + (-pnl) if rules.loss_offset_allowed else carry
        taxable = Decimal("0")
    else:
        offset = min(carry, pnl) if rules.loss_offset_allowed else Decimal("0")
        taxable = pnl - offset
        ending_loss = carry - offset

    income_tax = taxable * rules.realized_gain_rate
    transaction_tax = period.sale_notional * rules.transaction_tax_bps / Decimal("10000")
    return TaxAccrual(
        taxable_gain=taxable,
        income_tax=income_tax,
        transaction_tax=transaction_tax,
        ending_loss_carryforward=ending_loss,
        rule_id=rules.rule_id,
    )


__all__ = [
    "BrazilTaxRuleSet",
    "TaxAccrual",
    "TaxPeriodInput",
    "calculate_brazil_tax_accrual",
]

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .corporate_actions import CorporateActionType, normalize_corporate_actions


@dataclass(frozen=True)
class CorporateActionLifecycleAudit:
    rows: int
    declared_dates: int
    record_dates: int
    pay_dates: int
    unavailable_before_declaration: int
    ex_date_conflicts: int


def normalize_corporate_action_lifecycle(events: pd.DataFrame) -> tuple[pd.DataFrame, CorporateActionLifecycleAudit]:
    """Normalize corporate actions while preserving declaration/ex/record/pay dates.

    ``effective_date`` remains the canonical ex/effective date used for mechanical
    total-return adjustment.  The additional lifecycle dates are preserved because
    entitlement, cash settlement and point-in-time availability are distinct events.
    Missing lifecycle dates remain missing; they are never inferred from another date.
    """

    out = events.copy()
    if "ex_date" in out.columns:
        supplied_ex = pd.to_datetime(out["ex_date"], errors="coerce")
        supplied_effective = pd.to_datetime(out.get("effective_date"), errors="coerce")
        conflict = supplied_ex.notna() & supplied_effective.notna() & supplied_ex.ne(supplied_effective)
        if conflict.any():
            raise ValueError(f"ex_date conflicts with effective_date on {int(conflict.sum())} rows")
        if "effective_date" not in out.columns:
            out["effective_date"] = supplied_ex
        else:
            out["effective_date"] = supplied_effective.fillna(supplied_ex)
    elif "effective_date" in out.columns:
        out["ex_date"] = out["effective_date"]

    normalized = normalize_corporate_actions(out)
    normalized["ex_date"] = pd.to_datetime(normalized["effective_date"], errors="coerce")

    for column in ("declared_date", "record_date", "pay_date"):
        if column not in normalized.columns:
            normalized[column] = pd.NaT
        normalized[column] = pd.to_datetime(normalized[column], errors="coerce")

    available = pd.to_datetime(normalized["available_from"], errors="coerce", utc=True)
    declared = pd.to_datetime(normalized["declared_date"], errors="coerce", utc=True)
    known_before_declaration = declared.notna() & (available < declared)
    if known_before_declaration.any():
        raise ValueError(
            "available_from cannot precede declared_date for a declared corporate action"
        )

    cash_types = normalized["action_type"].isin(
        [CorporateActionType.CASH_DIVIDEND.value, CorporateActionType.INTEREST_ON_EQUITY.value]
    )
    pay_before_ex = (
        cash_types
        & normalized["pay_date"].notna()
        & normalized["ex_date"].notna()
        & (normalized["pay_date"] < normalized["ex_date"])
    )
    if pay_before_ex.any():
        raise ValueError("cash distribution pay_date cannot precede ex_date")

    audit = CorporateActionLifecycleAudit(
        rows=len(normalized),
        declared_dates=int(normalized["declared_date"].notna().sum()),
        record_dates=int(normalized["record_date"].notna().sum()),
        pay_dates=int(normalized["pay_date"].notna().sum()),
        unavailable_before_declaration=int(known_before_declaration.sum()),
        ex_date_conflicts=0,
    )
    return normalized, audit


def cash_payments_known_asof(
    events: pd.DataFrame,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Return cash distributions known by cutoff that have an explicit pay date.

    This is intentionally separate from ex-date total-return adjustment.  It can feed
    a cash ledger without pretending that declaration, entitlement and payment occur
    on the same date.
    """

    normalized, _ = normalize_corporate_action_lifecycle(events)
    cutoff_ts = pd.to_datetime(cutoff, errors="raise", utc=True)
    available = pd.to_datetime(normalized["available_from"], errors="raise", utc=True)
    cash = normalized["action_type"].isin(
        [CorporateActionType.CASH_DIVIDEND.value, CorporateActionType.INTEREST_ON_EQUITY.value]
    )
    return normalized.loc[cash & available.le(cutoff_ts) & normalized["pay_date"].notna()].copy().reset_index(drop=True)

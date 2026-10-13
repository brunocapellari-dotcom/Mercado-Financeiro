import pandas as pd
import pytest

from mercado_financeiro.pit import (
    cash_payments_known_asof,
    normalize_corporate_action_lifecycle,
)


def _cash_event() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": ["ISIN:BRTESTACNOR0"],
            "effective_date": ["2026-04-10"],
            "ex_date": ["2026-04-10"],
            "action_type": ["cash_dividend"],
            "available_from": ["2026-04-01T18:00:00Z"],
            "declared_date": ["2026-04-01"],
            "record_date": ["2026-04-09"],
            "pay_date": ["2026-04-20"],
            "cash_per_share": [1.25],
            "share_ratio": [1.0],
        }
    )


def test_lifecycle_preserves_distinct_corporate_action_dates():
    normalized, audit = normalize_corporate_action_lifecycle(_cash_event())
    row = normalized.iloc[0]
    assert row["declared_date"] == pd.Timestamp("2026-04-01")
    assert row["record_date"] == pd.Timestamp("2026-04-09")
    assert row["ex_date"] == pd.Timestamp("2026-04-10")
    assert row["pay_date"] == pd.Timestamp("2026-04-20")
    assert audit.declared_dates == 1
    assert audit.record_dates == 1
    assert audit.pay_dates == 1


def test_cash_payment_is_not_visible_before_source_availability():
    events = _cash_event()
    before = cash_payments_known_asof(events, "2026-03-31T23:59:59Z")
    after = cash_payments_known_asof(events, "2026-04-01T18:00:00Z")
    assert before.empty
    assert len(after) == 1
    assert after.loc[0, "pay_date"] == pd.Timestamp("2026-04-20")


def test_lifecycle_rejects_conflicting_ex_date_and_effective_date():
    events = _cash_event()
    events.loc[0, "ex_date"] = "2026-04-11"
    with pytest.raises(ValueError, match="ex_date conflicts"):
        normalize_corporate_action_lifecycle(events)


def test_lifecycle_rejects_knowledge_before_declaration_and_payment_before_ex():
    events = _cash_event()
    events.loc[0, "available_from"] = "2026-03-31T18:00:00Z"
    with pytest.raises(ValueError, match="cannot precede declared_date"):
        normalize_corporate_action_lifecycle(events)

    events = _cash_event()
    events.loc[0, "pay_date"] = "2026-04-09"
    with pytest.raises(ValueError, match="pay_date cannot precede ex_date"):
        normalize_corporate_action_lifecycle(events)

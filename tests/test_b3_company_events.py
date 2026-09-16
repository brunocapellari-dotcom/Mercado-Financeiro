from __future__ import annotations

import json

import pandas as pd

from mercado_financeiro.b3.company_events import (
    b3_cash_actions_to_canonical,
    encode_b3_company_request,
    parse_b3_company_events,
)
from mercado_financeiro.pit import normalize_corporate_action_lifecycle


def _payload() -> bytes:
    return json.dumps(
        [
            {
                "cashDividends": [
                    {
                        "assetIssued": "PETR4",
                        "paymentDate": "20/05/2025",
                        "rate": "1,25",
                        "relatedTo": "2025",
                        "approvedOn": "10/04/2025",
                        "isinCode": "BRPETRACNPR6",
                        "label": "DIVIDENDO",
                        "lastDatePrior": "30/04/2025",
                        "remarks": "",
                    }
                ],
                "stockDividends": [
                    {
                        "assetIssued": "BRPETRACNOR9",
                        "factor": "2,0",
                        "approvedOn": "10/04/2025",
                        "isinCode": "BRPETRACNOR9",
                        "label": "DESDOBRAMENTO",
                        "lastDatePrior": "30/04/2025",
                    }
                ],
                "subscriptions": [
                    {
                        "assetIssued": "BRPETRACNOR9",
                        "percentage": "10,0",
                        "priceUnit": "20,50",
                        "subscriptionDate": "30/06/2025",
                        "approvedOn": "10/04/2025",
                        "isinCode": "BRPETRACNOR9",
                        "label": "SUBSCRICAO",
                        "lastDatePrior": "30/04/2025",
                    }
                ],
            }
        ]
    ).encode()


def test_b3_request_encoding_rejects_non_company_tokens():
    token = encode_b3_company_request("petr")
    assert isinstance(token, str)
    try:
        encode_b3_company_request("../PETR")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe issuing-company code accepted")


def test_parse_company_events_preserves_current_snapshot_availability():
    events, audit = parse_b3_company_events(
        _payload(),
        issuing_company="PETR",
        retrieved_at=pd.Timestamp("2026-09-16T12:00:00Z"),
    )
    assert audit.rows == 3
    assert audit.cash_rows == 1
    assert audit.stock_rows == 1
    assert audit.subscription_rows == 1
    assert events.loc[0, "available_from"] == pd.Timestamp("2026-09-16T12:00:00Z")
    cash = events.loc[events["event_family"].eq("cash")].iloc[0]
    assert cash["security_id"] == "ISIN:BRPETRACNPR6"
    assert cash["cash_per_share_raw"] == 1.25
    assert cash["last_date_prior"] == pd.Timestamp("2025-04-30")


def test_cash_action_ex_date_is_next_observed_session_not_calendar_day():
    events, _ = parse_b3_company_events(
        _payload(),
        issuing_company="PETR",
        retrieved_at=pd.Timestamp("2026-09-16T12:00:00Z"),
    )
    canonical, unresolved = b3_cash_actions_to_canonical(
        events,
        observed_sessions=[
            "2025-04-30",
            "2025-05-02",
            "2025-05-05",
        ],
    )
    assert unresolved.empty
    row = canonical.iloc[0]
    assert row["effective_date"] == pd.Timestamp("2025-05-02")
    assert row["action_type"] == "cash_dividend"
    assert row["cash_per_share"] == 1.25
    assert row["evidence_mode"] == "historical_reconciliation_only"

    normalized, audit = normalize_corporate_action_lifecycle(canonical)
    assert audit.rows == 1
    assert normalized.loc[0, "effective_date"] == pd.Timestamp("2025-05-02")


def test_cash_action_without_next_observed_session_fails_closed():
    events, _ = parse_b3_company_events(
        _payload(),
        issuing_company="PETR",
        retrieved_at=pd.Timestamp("2026-09-16T12:00:00Z"),
    )
    canonical, unresolved = b3_cash_actions_to_canonical(
        events,
        observed_sessions=["2025-04-29", "2025-04-30"],
    )
    assert canonical.empty
    assert unresolved.loc[0, "canonical_status"] == "next_session_outside_observed_coverage"

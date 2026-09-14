from __future__ import annotations

import pandas as pd
import pytest

from mercado_financeiro.pit.shares import (
    normalize_dfp_shares_outstanding,
    shares_outstanding_asof,
)


def _row(**overrides):
    row = {
        "CNPJ_CIA": "00.000.000/0001-91",
        "DT_REFER": "2025-12-31",
        "VERSAO": "1",
        "available_from": "2026-03-15",
        "QT_ACAO_ORDIN_CAP_INTEGR": "100",
        "QT_ACAO_PREF_CAP_INTEGR": "50",
        "QT_ACAO_TOTAL_CAP_INTEGR": "150",
        "QT_ACAO_ORDIN_TESOURO": "10",
        "QT_ACAO_PREF_TESOURO": "5",
        "QT_ACAO_TOTAL_TESOURO": "15",
    }
    row.update(overrides)
    return row


def test_normalize_dfp_shares_subtracts_treasury():
    out = normalize_dfp_shares_outstanding(pd.DataFrame([_row()]))
    assert out.loc[0, "ordinary_outstanding"] == 90
    assert out.loc[0, "preferred_outstanding"] == 45
    assert out.loc[0, "total_outstanding"] == 135
    assert out.loc[0, "vintage_mode"] == "conservative_latest_snapshot"


def test_normalize_dfp_shares_fails_on_inconsistent_total():
    df = pd.DataFrame([_row(QT_ACAO_TOTAL_CAP_INTEGR="151")])
    with pytest.raises(ValueError, match="issued share totals mismatch"):
        normalize_dfp_shares_outstanding(df)


def test_shares_asof_blocks_future_filing_and_chooses_latest_reference():
    rows = [
        _row(DT_REFER="2023-12-31", available_from="2024-03-15", VERSAO="1"),
        _row(DT_REFER="2024-12-31", available_from="2025-03-20", VERSAO="1"),
        _row(DT_REFER="2025-12-31", available_from="2026-03-15", VERSAO="1"),
    ]
    normalized = normalize_dfp_shares_outstanding(pd.DataFrame(rows))

    at_2025_06 = shares_outstanding_asof(normalized, "2025-06-30")
    assert len(at_2025_06) == 1
    assert at_2025_06.loc[0, "reference_date"] == pd.Timestamp("2024-12-31")

    at_2026_06 = shares_outstanding_asof(normalized, "2026-06-30")
    assert at_2026_06.loc[0, "reference_date"] == pd.Timestamp("2025-12-31")


def test_shares_asof_keeps_issuers_independent():
    rows = [
        _row(CNPJ_CIA="A", DT_REFER="2024-12-31", available_from="2025-03-01"),
        _row(CNPJ_CIA="B", DT_REFER="2023-12-31", available_from="2024-03-01"),
    ]
    normalized = normalize_dfp_shares_outstanding(pd.DataFrame(rows))
    out = shares_outstanding_asof(normalized, "2025-06-01")
    assert set(out["issuer_id"]) == {"A", "B"}

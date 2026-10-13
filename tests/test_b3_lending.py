from datetime import datetime, timezone

import pandas as pd
import pytest

from mercado_financeiro.data import AcquisitionContext, B3SecuritiesLendingSource, VintageMode, asof
from mercado_financeiro.security import RawEvidenceVault


OPEN_POSITION = (
    "RptDt;TckrSymb;ISIN;Asst;BalQty;TradAvrgPric;PricFctr;BalVal\n"
    "2026-09-18;PETR4;BRPETRACNPR6;PETR;1000;31.50;1;31500\n"
    "2026-09-18;BOVA11;;BOVA;500;;1;60000\n"
).encode("utf-8")

LOAN_BALANCE = (
    "RptDt;TckrSymb;ISIN;Asst;QtyCtrctsDay;QtyShrDay;ValCtrctsDay;"
    "DnrMinRate;DnrAvrgRate;DnrMaxRate;TakrMinRate;TakrAvrgRate;TakrMaxRate;MktNm\n"
    "2026-09-18;PETR4;BRPETRACNPR6;PETR;12;12000;378000;"
    "0.01;0.02;0.03;0.015;0.025;0.035;Eletronico D+1\n"
).encode("utf-8")


def test_b3_lending_open_positions_preserve_optional_isin_and_fail_closed_identity():
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    dataset = B3SecuritiesLendingSource().parse_open_positions(
        OPEN_POSITION,
        source_url="https://www.b3.com.br/regulatory/LendingOpenPositionFile_20260918.csv",
        retrieved_at=retrieved,
        upstream_id="LendingOpenPositionFile_20260918.csv",
    )

    assert dataset.vintage_mode is VintageMode.CONSERVATIVE_RETRIEVAL
    petr = dataset.frame.loc[dataset.frame["ticker"].eq("PETR4")].iloc[0]
    bova = dataset.frame.loc[dataset.frame["ticker"].eq("BOVA11")].iloc[0]
    assert petr["security_id"] == "ISIN:BRPETRACNPR6"
    assert petr["identity_status"] == "exact_isin"
    assert bova["identity_status"] == "ticker_requires_resolution"
    assert pd.isna(bova["security_id"])
    assert bova["balance_quantity"] == 500
    assert pd.isna(bova["trade_average_price"])
    assert asof(dataset.frame, "2026-09-20T23:59:59Z").empty
    assert len(asof(dataset.frame, retrieved)) == 2


def test_b3_loan_balance_requires_exact_isin_and_parses_rates():
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    dataset = B3SecuritiesLendingSource().parse_loan_balance(
        LOAN_BALANCE,
        source_url="https://www.b3.com.br/regulatory/LoanBalanceFile_20260918.csv",
        retrieved_at=retrieved,
    )
    row = dataset.frame.iloc[0]
    assert row["security_id"] == "ISIN:BRPETRACNPR6"
    assert row["contracts_day"] == 12
    assert row["shares_day"] == 12000
    assert row["donor_average_rate"] == pytest.approx(0.02)
    assert row["taker_average_rate"] == pytest.approx(0.025)


def test_b3_lending_rejects_schema_drift():
    payload = b"RptDt;TckrSymb;ISIN\n2026-09-18;PETR4;BRPETRACNPR6\n"
    with pytest.raises(ValueError, match="schema drift"):
        B3SecuritiesLendingSource().parse_open_positions(
            payload,
            source_url="https://www.b3.com.br/regulatory/file.csv",
            retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )


def test_b3_lending_rejects_invalid_nonblank_isin():
    bad = OPEN_POSITION.replace(b"BRPETRACNPR6", b"INVALID")
    with pytest.raises(ValueError, match="invalid identifiers"):
        B3SecuritiesLendingSource().parse_open_positions(
            bad,
            source_url="https://www.b3.com.br/regulatory/file.csv",
            retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )


def test_b3_lending_preserves_raw_acquisition_receipt(tmp_path):
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    vault = RawEvidenceVault(tmp_path / "raw")
    source = B3SecuritiesLendingSource(
        acquisition=AcquisitionContext(
            raw_vault=vault,
            run_id="b3-lending-test",
            commit_sha="abcdef1",
        )
    )
    dataset = source.parse_open_positions(
        OPEN_POSITION,
        source_url="https://www.b3.com.br/regulatory/LendingOpenPositionFile_20260918.csv",
        retrieved_at=retrieved,
        upstream_id="LendingOpenPositionFile_20260918.csv",
    )

    assert dataset.raw_receipt_id is not None
    assert vault.read_payload(dataset.sha256) == OPEN_POSITION
    receipt = vault.read_receipt(dataset.raw_receipt_id)
    assert '"parser_version":"b3-lending-open-position-v1"' in receipt
    assert '"run_id":"b3-lending-test"' in receipt

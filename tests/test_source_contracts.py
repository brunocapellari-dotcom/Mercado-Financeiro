import pandas as pd

from mercado_financeiro.data.source_contracts import (
    COTAHIST_CONTRACT,
    CVM_FUNDAMENTALS_CONTRACT,
    CVM_FUND_DAILY_CONTRACT,
    CVM_FUND_HOLDINGS_CONTRACT,
    CVM_FUND_EQUITY_AGGREGATE_CONTRACT,
    get_financial_source_contract,
)


def test_cotahist_contract_accepts_canonical_positive_row():
    frame = pd.DataFrame(
        [
            {
                "trade_date": "2026-09-18",
                "ticker": "PETR4",
                "security_id": "ISIN:BRPETRACNPR6",
                "close_price": 31.25,
                "quotation_factor": 1,
                "trades": 100,
                "quantity": 10000,
                "financial_volume": 312500.0,
            }
        ]
    )
    result = COTAHIST_CONTRACT.evaluate(frame)
    assert result.passed


def test_cotahist_contract_rejects_negative_price():
    frame = pd.DataFrame(
        [
            {
                "trade_date": "2026-09-18",
                "ticker": "PETR4",
                "security_id": "ISIN:BRPETRACNPR6",
                "close_price": -1.0,
                "quotation_factor": 1,
                "trades": 100,
                "quantity": 10000,
                "financial_volume": 100.0,
            }
        ]
    )
    result = COTAHIST_CONTRACT.evaluate(frame)
    assert not result.passed
    assert any("out_of_range:close_price" in value for value in result.violations)


def test_cvm_contract_rejects_lookahead_and_future_information():
    frame = pd.DataFrame(
        [
            {
                "issuer_id": "CNPJ:1",
                "metric": "revenue",
                "value": 100.0,
                "reference_date": "2026-06-30T00:00:00Z",
                "available_from": "2026-08-01T00:00:00Z",
                "filing_version": 1,
                "source": "CVM",
            }
        ]
    )
    before_publication = CVM_FUNDAMENTALS_CONTRACT.evaluate(
        frame,
        as_of=pd.Timestamp("2026-07-31T23:59:59Z"),
    )
    assert not before_publication.passed
    assert "future_information_rows=1" in before_publication.violations

    bad = frame.copy()
    bad.loc[0, "available_from"] = "2026-06-01T00:00:00Z"
    result = CVM_FUNDAMENTALS_CONTRACT.evaluate(bad)
    assert not result.passed
    assert "availability_before_reference=1" in result.violations


def test_source_contract_registry_is_explicit():
    assert get_financial_source_contract("cotahist") is COTAHIST_CONTRACT


def test_cvm_fund_daily_contract_rejects_future_restatement_in_historical_asof():
    frame = pd.DataFrame(
        [
            {
                "fund_id": "00.000.000/0001-00",
                "reference_date": "2026-09-18T00:00:00Z",
                "total_portfolio": 1100.0,
                "nav": 1000.0,
                "quota_value": 1.1,
                "inflows": 50.0,
                "outflows": 20.0,
                "shareholders": 100,
                "available_from": "2026-09-21T12:00:00Z",
                "source_retrieved_at": "2026-09-21T12:00:00Z",
                "source_sha256": "a" * 64,
            }
        ]
    )
    historical = CVM_FUND_DAILY_CONTRACT.evaluate(
        frame,
        as_of=pd.Timestamp("2026-09-20T23:59:59Z"),
    )
    assert not historical.passed
    assert "future_information_rows=1" in historical.violations

    current = CVM_FUND_DAILY_CONTRACT.evaluate(
        frame,
        as_of=pd.Timestamp("2026-09-21T12:00:00Z"),
    )
    assert current.passed


def test_cvm_equity_holdings_contract_marks_future_snapshot_as_unavailable():
    frame = pd.DataFrame(
        [
            {
                "reference_date": "2026-08-31T00:00:00Z",
                "asset_code": "PETR4",
                "quantity": 15.0,
                "market_value": 375.0,
                "fund_count": 2,
                "coverage_status": "public_detail_only_confidential_positions_exist",
                "available_from": "2026-09-21T12:00:00Z",
                "source_retrieved_at": "2026-09-21T12:00:00Z",
                "source_sha256": "a" * 64,
            }
        ]
    )
    result = CVM_FUND_EQUITY_AGGREGATE_CONTRACT.evaluate(
        frame,
        as_of=pd.Timestamp("2026-09-20T23:59:59Z"),
    )
    assert not result.passed
    assert "future_information_rows=1" in result.violations


def test_cvm_row_holdings_contract_does_not_invent_unique_grain():
    frame = pd.DataFrame(
        [
            {
                "fund_id": "00000000000100",
                "reference_date": "2026-08-31T00:00:00Z",
                "block": "BLC_4",
                "asset_code": "PETR4",
                "source_member": "cda_fi_BLC_4_202608.csv",
                "public_detail_only": True,
                "available_from": "2026-09-21T12:00:00Z",
                "source_retrieved_at": "2026-09-21T12:00:00Z",
                "source_sha256": "b" * 64,
            },
            {
                "fund_id": "00000000000100",
                "reference_date": "2026-08-31T00:00:00Z",
                "block": "BLC_4",
                "asset_code": "PETR4",
                "source_member": "cda_fi_BLC_4_202608.csv",
                "public_detail_only": True,
                "available_from": "2026-09-21T12:00:00Z",
                "source_retrieved_at": "2026-09-21T12:00:00Z",
                "source_sha256": "b" * 64,
            },
        ]
    )
    result = CVM_FUND_HOLDINGS_CONTRACT.evaluate(
        frame,
        as_of=pd.Timestamp("2026-09-21T12:00:00Z"),
    )
    assert result.passed

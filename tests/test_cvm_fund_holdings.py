from datetime import datetime, timezone
from io import BytesIO
import zipfile

import pandas as pd

from mercado_financeiro.data import CVMFundHoldingsSource, VintageMode, asof


def _payload() -> bytes:
    header = (
        "CNPJ_FUNDO_CLASSE;DT_COMPTC;TP_APLIC;TP_ATIVO;CD_ATIVO;"
        "EMISSOR;CNPJ_EMISSOR;TP_NEGOC;QT_POS_FINAL;VL_MERC_POS_FINAL\n"
    )
    rows = (
        "00.000.000/0001-00;2026-08-31;Acoes;Acao;PETR4;"
        "PETROBRAS;33000167000101;Bolsa;10;250\n"
        "11.111.111/0001-11;2026-08-31;Acoes;Acao;PETR4;"
        "PETROBRAS;33000167000101;Bolsa;5;125\n"
        "00.000.000/0001-00;2026-08-31;Acoes;Acao;VALE3;"
        "VALE;33459258000110;Bolsa;2;120\n"
    )
    confidential = (
        "CNPJ_FUNDO_CLASSE;DT_COMPTC;TP_APLIC;VL_MERC_POS_FINAL\n"
        "22.222.222/0001-22;2026-08-31;CONFID;999\n"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cda_fi_BLC_4_202608.csv", (header + rows).encode("latin-1"))
        zf.writestr("cda_fi_CONFID_202608.csv", confidential.encode("latin-1"))
    return buffer.getvalue()


def test_cvm_holdings_filters_fund_and_preserves_conservative_availability(monkeypatch):
    payload = _payload()
    monkeypatch.setattr(
        "mercado_financeiro.data.cvm_fund_holdings.download_https",
        lambda url, policy: payload,
    )
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    dataset = CVMFundHoldingsSource().fetch_for_funds(
        2026,
        8,
        fund_ids=["00.000.000/0001-00"],
        retrieved_at=retrieved,
    )

    assert dataset.vintage_mode is VintageMode.CONSERVATIVE_RETRIEVAL
    assert set(dataset.frame["asset_code"]) == {"PETR4", "VALE3"}
    assert set(dataset.frame["fund_id"]) == {"00000000000100"}
    assert dataset.frame["public_detail_only"].all()
    assert asof(dataset.frame, "2026-09-20T23:59:59Z").empty
    assert len(asof(dataset.frame, retrieved)) == 2


def test_cvm_holdings_equity_aggregate_tracks_disclosed_coverage(monkeypatch):
    payload = _payload()
    monkeypatch.setattr(
        "mercado_financeiro.data.cvm_fund_holdings.download_https",
        lambda url, policy: payload,
    )
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    dataset = CVMFundHoldingsSource().fetch_equity_aggregate(
        2026,
        8,
        retrieved_at=retrieved,
    )

    petr = dataset.frame.loc[dataset.frame["asset_code"].eq("PETR4")].iloc[0]
    assert petr["quantity"] == 15.0
    assert petr["market_value"] == 375.0
    assert petr["fund_count"] == 2
    assert petr["coverage_status"] == "public_detail_only_confidential_positions_exist"
    assert dataset.frame["available_from"].eq(pd.Timestamp(retrieved)).all()

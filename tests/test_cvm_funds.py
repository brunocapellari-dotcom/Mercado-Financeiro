from datetime import datetime, timezone
from io import BytesIO
import zipfile

import pandas as pd

from mercado_financeiro.data import CVMFundDailySource, VintageMode, asof


def _payload() -> bytes:
    csv = (
        "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DT_COMPTC;VL_TOTAL;VL_QUOTA;"
        "VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
        "FI;00.000.000/0001-00;2026-09-18;1100.00;1.10;1000.00;50.00;20.00;100\n"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inf_diario_fi_202609.csv", csv.encode("latin-1"))
    return buffer.getvalue()


def test_cvm_fund_daily_is_conservative_pit_not_historical_backfill(monkeypatch):
    payload = _payload()
    monkeypatch.setattr(
        "mercado_financeiro.data.cvm_funds.download_https",
        lambda url, policy: payload,
    )
    retrieved = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    dataset = CVMFundDailySource().fetch_month(2026, 9, retrieved_at=retrieved)

    assert dataset.vintage_mode is VintageMode.CONSERVATIVE_RETRIEVAL
    assert dataset.frame.loc[0, "reference_date"] == pd.Timestamp("2026-09-18", tz="UTC")
    assert dataset.frame.loc[0, "available_from"] == pd.Timestamp(retrieved)
    assert dataset.frame.loc[0, "nav"] == 1000.0
    assert dataset.frame.loc[0, "inflows"] == 50.0
    assert dataset.frame.loc[0, "outflows"] == 20.0
    assert asof(dataset.frame, "2026-09-20T23:59:59Z").empty
    assert len(asof(dataset.frame, retrieved)) == 1

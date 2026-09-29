from datetime import datetime, timezone
import json

import pandas as pd

from mercado_financeiro.data.bcb_olinda import (
    BCBMarketExpectationsSource,
    BCBPtaxSource,
    FocusEndpoint,
)
from mercado_financeiro.data.historical import VintageMode, asof


def test_ptax_preserves_official_publication_timestamp(monkeypatch):
    payload = json.dumps(
        {
            "value": [
                {
                    "cotacaoCompra": 5.10,
                    "cotacaoVenda": 5.11,
                    "dataHoraCotacao": "2026-09-28 13:05:00.000",
                }
            ]
        }
    ).encode()
    monkeypatch.setattr(
        "mercado_financeiro.data.bcb_olinda.download_https",
        lambda url, policy: payload,
    )
    retrieved = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    dataset = BCBPtaxSource().fetch("2026-09-28", "2026-09-28", retrieved_at=retrieved)
    assert dataset.vintage_mode == VintageMode.PUBLICATION_GATED
    row = dataset.frame.iloc[0]
    assert row["sell"] == 5.11
    assert row["available_from"] == row["reference_date"]
    assert not asof(dataset.frame, "2026-09-28T12:00:00Z").shape[0]


def test_focus_historical_rows_are_not_backfilled_as_if_publication_time_were_known(monkeypatch):
    payload = json.dumps(
        {
            "value": [
                {
                    "Indicador": "IPCA",
                    "Data": "2026-09-25",
                    "DataReferencia": "2027",
                    "Media": 4.1,
                    "Mediana": 4.0,
                    "DesvioPadrao": 0.3,
                    "Minimo": 3.5,
                    "Maximo": 4.8,
                    "numeroRespondentes": 100,
                    "baseCalculo": 0,
                }
            ]
        }
    ).encode()
    monkeypatch.setattr(
        "mercado_financeiro.data.bcb_olinda.download_https",
        lambda url, policy: payload,
    )
    retrieved = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    dataset = BCBMarketExpectationsSource().fetch(
        FocusEndpoint.ANNUAL,
        indicator="IPCA",
        retrieved_at=retrieved,
    )
    assert dataset.vintage_mode == VintageMode.CONSERVATIVE_RETRIEVAL
    assert dataset.frame.loc[0, "forecast_reference"] == "2027"
    assert dataset.frame.loc[0, "available_from"] == pd.Timestamp(retrieved)
    assert asof(dataset.frame, "2026-09-28T23:59:59Z").empty


def test_focus_url_rejects_unknown_endpoint_and_escapes_indicator():
    source = BCBMarketExpectationsSource()
    url = source.build_url(
        FocusEndpoint.ANNUAL,
        start="2026-09-01",
        end="2026-09-29",
        indicator="IPCA",
    )
    assert "ExpectativasMercadoAnuais" in url
    assert "%24filter" in url or "$filter" in url

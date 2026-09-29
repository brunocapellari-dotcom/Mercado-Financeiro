from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import urlencode

import pandas as pd

from mercado_financeiro.security import DownloadPolicy, download_https
from .historical import HistoricalDataset, VintageMode, require_pit_columns


class FocusEndpoint(str, Enum):
    ANNUAL = "ExpectativasMercadoAnuais"
    MONTHLY = "ExpectativaMercadoMensais"
    QUARTERLY = "ExpectativasMercadoTrimestrais"
    SELIC = "ExpectativasMercadoSelic"
    INFLATION_12M = "ExpectativasMercadoInflacao12Meses"
    INFLATION_24M = "ExpectativasMercadoInflacao24Meses"


def _aware_utc(value: datetime | None) -> datetime:
    out = value or datetime.now(timezone.utc)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return out.astimezone(timezone.utc)


def _odata_payload(payload: bytes) -> list[dict[str, object]]:
    try:
        decoded = json.load(BytesIO(payload))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid BCB Olinda JSON") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("value"), list):
        raise ValueError("BCB Olinda response must contain a value list")
    records = decoded["value"]
    if any(not isinstance(item, dict) for item in records):
        raise ValueError("BCB Olinda value entries must be objects")
    return records  # type: ignore[return-value]


def _brazil_timestamp_to_utc(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("America/Sao_Paulo")
    return ts.tz_convert("UTC")


class BCBPtaxSource:
    """Official PTAX USD/BRL collector with row-level publication timestamps."""

    name = "BCB_PTAX"
    base_url = (
        "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
        "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    )

    def __init__(self, *, policy: DownloadPolicy | None = None) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"olinda.bcb.gov.br"}),
            timeout_seconds=30.0,
            max_bytes=50_000_000,
        )

    def build_url(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> str:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if pd.isna(start_ts) or pd.isna(end_ts) or end_ts < start_ts:
            raise ValueError("PTAX date interval is invalid")
        params = {
            "@dataInicial": f"'{start_ts.strftime('%m-%d-%Y')}'",
            "@dataFinalCotacao": f"'{end_ts.strftime('%m-%d-%Y')}'",
            "$top": "10000",
            "$format": "json",
            "$select": "cotacaoCompra,cotacaoVenda,dataHoraCotacao",
        }
        return self.base_url + "?" + urlencode(params, safe="'$,@")

    def fetch(
        self,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        url = self.build_url(start, end)
        payload = download_https(url, self._policy)
        retrieved = _aware_utc(retrieved_at)
        digest = sha256(payload).hexdigest()
        frame = self._parse(payload)
        frame["source_retrieved_at"] = pd.Timestamp(retrieved)
        frame["source_sha256"] = digest
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset="USD_BRL_PTAX",
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.PUBLICATION_GATED,
            frame=frame,
        )

    @staticmethod
    def _parse(payload: bytes) -> pd.DataFrame:
        records = _odata_payload(payload)
        rows: list[dict[str, object]] = []
        for item in records:
            required = {"cotacaoCompra", "cotacaoVenda", "dataHoraCotacao"}
            if not required.issubset(item):
                raise ValueError("PTAX observation is missing required fields")
            buy = pd.to_numeric(item["cotacaoCompra"], errors="coerce")
            sell = pd.to_numeric(item["cotacaoVenda"], errors="coerce")
            if pd.isna(buy) or pd.isna(sell) or float(buy) <= 0 or float(sell) <= 0:
                raise ValueError("invalid PTAX quotation")
            published = _brazil_timestamp_to_utc(item["dataHoraCotacao"])
            rows.append(
                {
                    "reference_date": published,
                    "available_from": published,
                    "buy": float(buy),
                    "sell": float(sell),
                }
            )
        out = pd.DataFrame(
            rows,
            columns=["reference_date", "available_from", "buy", "sell"],
        )
        if out.duplicated(["reference_date"]).any():
            raise ValueError("duplicate PTAX publication timestamp")
        return out.sort_values("reference_date", kind="stable").reset_index(drop=True)


class BCBMarketExpectationsSource:
    """Official aggregated Focus statistics.

    Historical Olinda rows expose the collection date, but not a trustworthy
    publication timestamp for every vintage. The collector therefore fails
    conservatively: historical rows become usable only from the actual retrieval
    timestamp unless a separately audited publication ledger is introduced.
    """

    name = "BCB_FOCUS"
    base_url = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"

    def __init__(self, *, policy: DownloadPolicy | None = None) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"olinda.bcb.gov.br"}),
            timeout_seconds=45.0,
            max_bytes=100_000_000,
        )

    def build_url(
        self,
        endpoint: FocusEndpoint | str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        indicator: str | None = None,
        top: int = 10000,
    ) -> str:
        endpoint = endpoint if isinstance(endpoint, FocusEndpoint) else FocusEndpoint(endpoint)
        if top <= 0 or top > 100000:
            raise ValueError("top must be in [1, 100000]")
        filters: list[str] = []
        if start is not None:
            filters.append(f"Data ge '{pd.Timestamp(start).strftime('%Y-%m-%d')}'")
        if end is not None:
            filters.append(f"Data le '{pd.Timestamp(end).strftime('%Y-%m-%d')}'")
        if start is not None and end is not None and pd.Timestamp(end) < pd.Timestamp(start):
            raise ValueError("Focus date interval is invalid")
        if indicator is not None:
            clean = indicator.strip()
            if not clean:
                raise ValueError("indicator cannot be empty")
            filters.append("Indicador eq '" + clean.replace("'", "''") + "'")
        params: dict[str, str] = {"$top": str(top), "$format": "json"}
        if filters:
            params["$filter"] = " and ".join(filters)
        return f"{self.base_url}/{endpoint.value}?" + urlencode(params, safe="'$(),")

    def fetch(
        self,
        endpoint: FocusEndpoint | str,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        indicator: str | None = None,
        top: int = 10000,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        endpoint = endpoint if isinstance(endpoint, FocusEndpoint) else FocusEndpoint(endpoint)
        url = self.build_url(endpoint, start=start, end=end, indicator=indicator, top=top)
        payload = download_https(url, self._policy)
        retrieved = _aware_utc(retrieved_at)
        digest = sha256(payload).hexdigest()
        frame = self._parse(payload, retrieved_at=retrieved)
        frame["source_retrieved_at"] = pd.Timestamp(retrieved)
        frame["source_sha256"] = digest
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset=endpoint.value,
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=frame,
        )

    @staticmethod
    def _parse(payload: bytes, *, retrieved_at: datetime) -> pd.DataFrame:
        records = _odata_payload(payload)
        rows: list[dict[str, object]] = []
        retrieved = pd.Timestamp(retrieved_at)
        for item in records:
            if "Indicador" not in item or "Data" not in item:
                raise ValueError("Focus observation is missing Indicador/Data")
            collection_date = pd.to_datetime(item["Data"], errors="coerce", utc=True)
            if pd.isna(collection_date):
                raise ValueError("invalid Focus collection date")
            row: dict[str, object] = {
                "series_id": str(item["Indicador"]).strip(),
                "reference_date": collection_date,
                "available_from": retrieved,
                "forecast_reference": item.get(
                    "DataReferencia",
                    item.get("Reuniao", item.get("Suavizada")),
                ),
                "indicator_detail": item.get("IndicadorDetalhe"),
                "mean": pd.to_numeric(item.get("Media"), errors="coerce"),
                "median": pd.to_numeric(item.get("Mediana"), errors="coerce"),
                "stddev": pd.to_numeric(item.get("DesvioPadrao"), errors="coerce"),
                "minimum": pd.to_numeric(item.get("Minimo"), errors="coerce"),
                "maximum": pd.to_numeric(item.get("Maximo"), errors="coerce"),
                "respondents": pd.to_numeric(item.get("numeroRespondentes"), errors="coerce"),
                "calculation_base": pd.to_numeric(item.get("baseCalculo"), errors="coerce"),
            }
            if not row["series_id"]:
                raise ValueError("Focus indicator cannot be empty")
            rows.append(row)
        return pd.DataFrame.from_records(rows)


__all__ = ["BCBMarketExpectationsSource", "BCBPtaxSource", "FocusEndpoint"]

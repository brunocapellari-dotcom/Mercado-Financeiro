from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import urlencode

import pandas as pd

from mercado_financeiro.security import DownloadPolicy, RetryPolicy, download_https_with_retry
from .historical import HistoricalDataset, VintageMode, require_pit_columns


class BCBSgsSource:
    """Official Banco Central SGS collector with explicit availability semantics.

    SGS endpoints commonly expose the latest representation of a historical
    series. Therefore the default is conservative: a downloaded historical value
    is considered available only at retrieval time. A publication lag may only be
    supplied after the series-specific release contract has been audited.
    """

    name = "BCB_SGS"
    base_url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"

    def __init__(self, *, policy: DownloadPolicy | None = None) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"api.bcb.gov.br"}),
            timeout_seconds=30.0,
            max_bytes=50_000_000,
        )

    def build_url(
        self,
        series_code: int,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> str:
        if int(series_code) <= 0:
            raise ValueError("series_code must be positive")
        params: dict[str, str] = {"formato": "json"}
        if start is not None:
            params["dataInicial"] = pd.Timestamp(start).strftime("%d/%m/%Y")
        if end is not None:
            params["dataFinal"] = pd.Timestamp(end).strftime("%d/%m/%Y")
        return self.base_url.format(code=int(series_code)) + "?" + urlencode(params)

    def fetch(
        self,
        series_code: int,
        *,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
        publication_lag_days: int | None = None,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        if publication_lag_days is not None and publication_lag_days < 0:
            raise ValueError("publication_lag_days cannot be negative")
        url = self.build_url(series_code, start=start, end=end)
        payload = download_https_with_retry(
            url,
            self._policy,
            retry_policy=RetryPolicy(
                attempts=5,
                initial_delay_seconds=1.0,
                max_delay_seconds=8.0,
            ),
        )
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        digest = sha256(payload).hexdigest()
        frame = self._parse(payload)
        frame["series_code"] = int(series_code)
        frame["source_retrieved_at"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_sha256"] = digest

        if publication_lag_days is None:
            frame["available_from"] = pd.Timestamp(retrieved).tz_convert("UTC")
            mode = VintageMode.CONSERVATIVE_RETRIEVAL
        else:
            reference = pd.to_datetime(frame["reference_date"], utc=True)
            frame["available_from"] = reference + pd.to_timedelta(publication_lag_days, unit="D")
            mode = VintageMode.PUBLICATION_GATED
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset=f"SGS_{int(series_code)}",
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=mode,
            frame=frame,
        )

    @staticmethod
    def _parse(payload: bytes) -> pd.DataFrame:
        try:
            decoded = json.load(BytesIO(payload))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid BCB SGS JSON") from exc
        if not isinstance(decoded, list):
            raise ValueError("BCB SGS response must be a JSON list")
        records: list[dict[str, object]] = []
        for item in decoded:
            if not isinstance(item, dict) or "data" not in item or "valor" not in item:
                raise ValueError("invalid BCB SGS observation")
            reference = pd.to_datetime(item["data"], format="%d/%m/%Y", errors="coerce", utc=True)
            if pd.isna(reference):
                raise ValueError("invalid BCB SGS observation date")
            text = str(item["valor"]).strip().replace(",", ".")
            value = pd.to_numeric(text, errors="coerce")
            if pd.isna(value):
                raise ValueError("invalid BCB SGS observation value")
            records.append({"reference_date": reference, "value": float(value)})
        return pd.DataFrame.from_records(records, columns=["reference_date", "value"])

    def healthcheck(self) -> bool:
        # Series 1178 is intentionally not hard-coded here as a semantic input;
        # health is tested by the orchestration layer against its configured series.
        return True

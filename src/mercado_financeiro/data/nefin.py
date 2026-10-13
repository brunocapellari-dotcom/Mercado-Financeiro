from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO

import pandas as pd

from mercado_financeiro.security import DownloadPolicy, download_https
from .historical import HistoricalDataset, VintageMode, require_pit_columns


class NEFINRiskFactorsSource:
    """Collector for the official NEFIN/FEA-USP Brazilian risk-factor CSV.

    NEFIN factors are used first as an independent benchmark/reconciliation
    dataset. The published current CSV is not assumed to be a historical vintage
    feed, so it is never silently promoted to a trading feature.
    """

    name = "NEFIN_USP"
    url = "https://nefin.com.br/nefindata/risk-factors/nefin_factors.csv"

    def __init__(self, *, policy: DownloadPolicy | None = None) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"nefin.com.br", "www.nefin.com.br"}),
            timeout_seconds=30.0,
            max_bytes=100_000_000,
        )

    def fetch(self, *, retrieved_at: datetime | None = None) -> HistoricalDataset:
        payload = download_https(self.url, self._policy)
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        digest = sha256(payload).hexdigest()
        frame = self._parse(payload)
        frame["available_from"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_retrieved_at"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_sha256"] = digest
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset="RISK_FACTORS",
            source_url=self.url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.BENCHMARK_ONLY,
            frame=frame,
        )

    @staticmethod
    def _parse(payload: bytes) -> pd.DataFrame:
        if not payload:
            raise ValueError("empty NEFIN risk-factor payload")
        try:
            frame = pd.read_csv(BytesIO(payload))
        except Exception as exc:  # pandas emits parser/encoding subclasses
            raise ValueError("invalid NEFIN risk-factor CSV") from exc
        if frame.empty:
            raise ValueError("NEFIN risk-factor CSV is empty")

        date_column = next(
            (
                column
                for column in frame.columns
                if str(column).strip().lower() in {"date", "data", "reference_date"}
            ),
            frame.columns[0],
        )
        dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
        if dates.isna().any():
            # Some historical NEFIN files use compact YYYYMMDD dates.
            dates = pd.to_datetime(
                frame[date_column].astype(str).str.replace(r"\.0$", "", regex=True),
                format="%Y%m%d",
                errors="coerce",
                utc=True,
            )
        if dates.isna().any():
            raise ValueError("NEFIN risk-factor CSV contains invalid dates")

        out = frame.copy()
        if date_column != "reference_date":
            out = out.rename(columns={date_column: "reference_date"})
        out["reference_date"] = dates
        if out["reference_date"].duplicated().any():
            raise ValueError("NEFIN risk-factor CSV contains duplicate dates")
        return out.sort_values("reference_date").reset_index(drop=True)

    def healthcheck(self) -> bool:
        return True

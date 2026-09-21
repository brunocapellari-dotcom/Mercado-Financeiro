from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import zipfile

import pandas as pd

from mercado_financeiro.security.io import DownloadPolicy, download_https, validate_zip_bytes
from .acquisition import AcquisitionContext
from .historical import HistoricalDataset, VintageMode, require_pit_columns


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def _first(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    raise ValueError(f"CVM fund dataset missing all aliases: {names}")


def _read_zip_csvs(payload: bytes) -> pd.DataFrame:
    validate_zip_bytes(payload, max_members=30, max_total_uncompressed=1_500_000_000)
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                with zf.open(name) as raw:
                    part = pd.read_csv(raw, sep=";", encoding="latin-1", dtype=str, low_memory=False)
                part["__cvm_member"] = name
                frames.append(part)
    if not frames:
        raise ValueError("CVM fund ZIP contains no CSV members")
    return pd.concat(frames, ignore_index=True, sort=False)


class CVMFundDailySource:
    name = "CVM"
    base_url = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{year}{month:02d}.zip"

    def __init__(
        self,
        *,
        policy: DownloadPolicy | None = None,
        acquisition: AcquisitionContext | None = None,
    ) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"dados.cvm.gov.br"}),
            timeout_seconds=90.0,
            max_bytes=100_000_000,
        )
        self._acquisition = acquisition or AcquisitionContext()

    def fetch_month(self, year: int, month: int, *, retrieved_at: datetime | None = None) -> HistoricalDataset:
        if year < 2000 or not 1 <= month <= 12:
            raise ValueError("invalid year/month")
        url = self.base_url.format(year=year, month=month)
        payload = download_https(url, self._policy)
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        receipt_id = self._acquisition.preserve(
            payload,
            source_name=self.name,
            source_url=url,
            retrieved_at=retrieved,
            upstream_id=f"inf_diario_fi_{year}{month:02d}.zip",
            parser_version="cvm-fund-daily-v1",
            reference_time=f"{year}-{month:02d}-01",
            content_type="application/zip",
        )
        raw = _read_zip_csvs(payload)
        out = pd.DataFrame()
        out["fund_id"] = _first(raw, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO").astype(str).str.strip()
        out["reference_date"] = pd.to_datetime(_first(raw, "DT_COMPTC"), errors="coerce", utc=True)
        aliases = {
            "total_portfolio": ("VL_TOTAL",),
            "nav": ("VL_PATRIM_LIQ",),
            "quota_value": ("VL_QUOTA",),
            "inflows": ("CAPTC_DIA",),
            "outflows": ("RESG_DIA",),
            "shareholders": ("NR_COTST",),
        }
        for target, names in aliases.items():
            out[target] = _num(_first(raw, *names))
        if out["fund_id"].eq("").any() or out["reference_date"].isna().any():
            raise ValueError("CVM fund daily contains invalid fund/date")
        if out[list(aliases)].isna().any().any():
            raise ValueError("CVM fund daily contains invalid numeric values")
        out["available_from"] = pd.Timestamp(retrieved).tz_convert("UTC")
        out["source_retrieved_at"] = out["available_from"]
        out["source_sha256"] = sha256(payload).hexdigest()
        require_pit_columns(out)
        return HistoricalDataset(
            source=self.name,
            dataset=f"FI_INF_DIARIO_{year}{month:02d}",
            source_url=url,
            retrieved_at=retrieved,
            sha256=sha256(payload).hexdigest(),
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=out.sort_values(["reference_date", "fund_id"]).reset_index(drop=True),
            raw_receipt_id=receipt_id,
        )

    def healthcheck(self) -> bool:
        return True

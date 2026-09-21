from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from io import StringIO
import re

import pandas as pd

from .acquisition import AcquisitionContext
from .historical import HistoricalDataset, VintageMode, require_pit_columns


_ISIN_RE = re.compile(r"^[A-Z0-9]{12}$")


def _decode_csv(payload: bytes) -> tuple[str, str]:
    if not payload:
        raise ValueError("B3 lending CSV payload must not be empty")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    semicolons = first_line.count(";")
    commas = first_line.count(",")
    if semicolons > commas and semicolons:
        delimiter = ";"
    elif commas:
        delimiter = ","
    else:
        raise ValueError("unable to detect B3 lending CSV delimiter")
    return text, delimiter


def _read_csv(payload: bytes) -> pd.DataFrame:
    text, delimiter = _decode_csv(payload)
    frame = pd.read_csv(StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    frame.columns = [str(column).strip() for column in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError("B3 lending CSV contains duplicate columns")
    return frame


def _required(frame: pd.DataFrame, names: set[str], *, dataset: str) -> None:
    missing = names - set(frame.columns)
    if missing:
        raise ValueError(f"{dataset} schema drift; missing columns: {sorted(missing)}")


def _number(series: pd.Series, *, field: str, required: bool = True) -> pd.Series:
    text = series.astype(str).str.strip()
    normalized = text.str.replace(",", ".", regex=False)
    parsed = pd.to_numeric(normalized.where(text.ne(""), None), errors="coerce")
    if required and parsed.isna().any():
        raise ValueError(f"B3 lending field {field} contains null/invalid numeric values")
    invalid_nonblank = text.ne("") & parsed.isna()
    if invalid_nonblank.any():
        raise ValueError(f"B3 lending field {field} contains invalid numeric values")
    return parsed


def _reference_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series.astype(str).str.strip(), errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("B3 lending RptDt contains null/invalid dates")
    return parsed


def _ticker(series: pd.Series) -> pd.Series:
    values = series.astype(str).str.strip().str.upper()
    if values.eq("").any():
        raise ValueError("B3 lending TckrSymb must not be blank")
    return values


def _isin(series: pd.Series, *, required: bool) -> pd.Series:
    values = series.astype(str).str.strip().str.upper()
    invalid = values.ne("") & ~values.str.fullmatch(_ISIN_RE)
    if invalid.any():
        raise ValueError("B3 lending ISIN contains invalid identifiers")
    if required and values.eq("").any():
        raise ValueError("B3 lending ISIN is required for LoanBalanceFile")
    return values.replace("", pd.NA)


class B3SecuritiesLendingSource:
    """Parser boundary for B3 regulatory securities-lending CSV files.

    Network acquisition is intentionally separate because the public B3 download
    surface is not treated as a stable API contract. Callers supply the official
    bytes and source URL; this parser validates the documented taxonomy, preserves
    raw evidence when configured, and uses retrieval time as conservative PIT
    availability.
    """

    name = "B3"

    def __init__(self, *, acquisition: AcquisitionContext | None = None) -> None:
        self._acquisition = acquisition or AcquisitionContext()

    def parse_open_positions(
        self,
        payload: bytes,
        *,
        source_url: str,
        retrieved_at: datetime,
        upstream_id: str | None = None,
    ) -> HistoricalDataset:
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        raw = _read_csv(payload)
        required = {
            "RptDt",
            "TckrSymb",
            "ISIN",
            "Asst",
            "BalQty",
            "TradAvrgPric",
            "PricFctr",
            "BalVal",
        }
        _required(raw, required, dataset="LendingOpenPositionFile")

        out = pd.DataFrame()
        out["reference_date"] = _reference_date(raw["RptDt"])
        out["ticker"] = _ticker(raw["TckrSymb"])
        out["isin"] = _isin(raw["ISIN"], required=False)
        out["security_id"] = out["isin"].map(
            lambda value: f"ISIN:{value}" if pd.notna(value) else None
        )
        out["identity_status"] = out["isin"].map(
            lambda value: "exact_isin" if pd.notna(value) else "ticker_requires_resolution"
        )
        out["asset"] = raw["Asst"].astype(str).str.strip()
        if out["asset"].eq("").any():
            raise ValueError("B3 lending Asst must not be blank")
        out["balance_quantity"] = _number(raw["BalQty"], field="BalQty")
        out["trade_average_price"] = _number(
            raw["TradAvrgPric"], field="TradAvrgPric", required=False
        )
        out["price_factor"] = _number(raw["PricFctr"], field="PricFctr")
        out["balance_value"] = _number(raw["BalVal"], field="BalVal")
        if (out["balance_quantity"] < 0).any() or (out["balance_value"] < 0).any():
            raise ValueError("B3 lending open positions contain negative balances")
        if (out["price_factor"] <= 0).any():
            raise ValueError("B3 lending price factor must be positive")

        available = pd.Timestamp(retrieved_at).tz_convert("UTC")
        digest = sha256(payload).hexdigest()
        out["available_from"] = available
        out["source_retrieved_at"] = available
        out["source_sha256"] = digest
        receipt_id = self._acquisition.preserve(
            payload,
            source_name=self.name,
            source_url=source_url,
            retrieved_at=retrieved_at,
            upstream_id=upstream_id,
            parser_version="b3-lending-open-position-v1",
            reference_time=out["reference_date"].max().isoformat(),
            content_type="text/csv",
        )
        require_pit_columns(out)
        return HistoricalDataset(
            source=self.name,
            dataset="B3_LENDING_OPEN_POSITION",
            source_url=source_url,
            retrieved_at=retrieved_at,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=out.sort_values(["reference_date", "ticker", "isin"], na_position="last").reset_index(drop=True),
            raw_receipt_id=receipt_id,
        )

    def parse_loan_balance(
        self,
        payload: bytes,
        *,
        source_url: str,
        retrieved_at: datetime,
        upstream_id: str | None = None,
    ) -> HistoricalDataset:
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        raw = _read_csv(payload)
        required = {
            "RptDt",
            "TckrSymb",
            "ISIN",
            "Asst",
            "QtyCtrctsDay",
            "QtyShrDay",
            "ValCtrctsDay",
            "DnrMinRate",
            "DnrAvrgRate",
            "DnrMaxRate",
            "TakrMinRate",
            "TakrAvrgRate",
            "TakrMaxRate",
            "MktNm",
        }
        _required(raw, required, dataset="LoanBalanceFile")

        out = pd.DataFrame()
        out["reference_date"] = _reference_date(raw["RptDt"])
        out["ticker"] = _ticker(raw["TckrSymb"])
        out["isin"] = _isin(raw["ISIN"], required=True)
        out["security_id"] = "ISIN:" + out["isin"].astype(str)
        out["asset"] = raw["Asst"].astype(str).str.strip()
        out["market_name"] = raw["MktNm"].astype(str).str.strip()
        if out["asset"].eq("").any() or out["market_name"].eq("").any():
            raise ValueError("B3 LoanBalanceFile asset/market must not be blank")
        numeric_fields = {
            "contracts_day": "QtyCtrctsDay",
            "shares_day": "QtyShrDay",
            "contracts_value_day": "ValCtrctsDay",
            "donor_min_rate": "DnrMinRate",
            "donor_average_rate": "DnrAvrgRate",
            "donor_max_rate": "DnrMaxRate",
            "taker_min_rate": "TakrMinRate",
            "taker_average_rate": "TakrAvrgRate",
            "taker_max_rate": "TakrMaxRate",
        }
        for target, source in numeric_fields.items():
            out[target] = _number(raw[source], field=source)
        if (
            (out["contracts_day"] < 0).any()
            or (out["shares_day"] < 0).any()
            or (out["contracts_value_day"] < 0).any()
        ):
            raise ValueError("B3 LoanBalanceFile contains negative quantities/value")

        available = pd.Timestamp(retrieved_at).tz_convert("UTC")
        digest = sha256(payload).hexdigest()
        out["available_from"] = available
        out["source_retrieved_at"] = available
        out["source_sha256"] = digest
        receipt_id = self._acquisition.preserve(
            payload,
            source_name=self.name,
            source_url=source_url,
            retrieved_at=retrieved_at,
            upstream_id=upstream_id,
            parser_version="b3-loan-balance-v1",
            reference_time=out["reference_date"].max().isoformat(),
            content_type="text/csv",
        )
        require_pit_columns(out)
        return HistoricalDataset(
            source=self.name,
            dataset="B3_LOAN_BALANCE",
            source_url=source_url,
            retrieved_at=retrieved_at,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=out.sort_values(["reference_date", "ticker", "market_name"]).reset_index(drop=True),
            raw_receipt_id=receipt_id,
        )

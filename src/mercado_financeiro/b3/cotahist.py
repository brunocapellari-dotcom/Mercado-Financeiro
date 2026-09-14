from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
from pathlib import Path
import zipfile

import pandas as pd


_RECORD_LENGTH = 245
_REGULAR_SHARE_BDI_CODES = {"02", "05", "06", "07", "08", "09", "11"}


@dataclass(frozen=True)
class CotahistAudit:
    rows: int
    share_rows: int
    unique_dates: int
    unique_tickers: int
    unique_isins: int
    missing_isin_rows: int
    duplicate_security_date_rows: int


def _zip_payload(path: str | Path) -> bytes:
    """Accept a raw B3 ZIP or the one-file ZIP wrapper used by project archives."""
    payload = Path(path).read_bytes()
    with zipfile.ZipFile(BytesIO(payload)) as outer:
        names = outer.namelist()
        if len(names) == 1 and names[0].lower().endswith(".zip"):
            return outer.read(names[0])
    return payload


def _decimal(line: str, start: int, end: int, scale: int = 2) -> float:
    raw = line[start:end]
    if not raw.isdigit():
        raise ValueError(f"invalid numeric field at {start + 1}-{end}: {raw!r}")
    return int(raw) / (10**scale)


def _integer(line: str, start: int, end: int) -> int:
    raw = line[start:end]
    if not raw.isdigit():
        raise ValueError(f"invalid integer field at {start + 1}-{end}: {raw!r}")
    return int(raw)


def parse_cotahist_record(line: str) -> dict[str, object]:
    """Parse one official 245-byte COTAHIST record type 01.

    Positions follow the B3 historical quotations layout revision 01 (2017), whose
    record 01 layout includes trade date, ticker, market, prices, quotation factor and
    ISIN. Monetary price fields have two implied decimal places.
    """
    line = line.rstrip("\r\n")
    if len(line) != _RECORD_LENGTH:
        raise ValueError(f"COTAHIST record must have 245 chars, got {len(line)}")
    if line[0:2] != "01":
        raise ValueError(f"expected record type 01, got {line[0:2]!r}")

    quotation_factor = _integer(line, 210, 217)
    if quotation_factor <= 0:
        raise ValueError("quotation factor must be positive")

    close_quote = _decimal(line, 108, 121)
    isin = line[230:242].strip().upper()
    return {
        "trade_date": pd.Timestamp(line[2:10]),
        "bdi_code": line[10:12].strip(),
        "ticker": line[12:24].strip().upper(),
        "market_type": _integer(line, 24, 27),
        "issuer_short_name": line[27:39].strip(),
        "specification": line[39:49].strip().upper(),
        "term_days": line[49:52].strip(),
        "currency": line[52:56].strip(),
        "open_quote": _decimal(line, 56, 69),
        "high_quote": _decimal(line, 69, 82),
        "low_quote": _decimal(line, 82, 95),
        "average_quote": _decimal(line, 95, 108),
        "close_quote": close_quote,
        "best_bid_quote": _decimal(line, 121, 134),
        "best_ask_quote": _decimal(line, 134, 147),
        "trades": _integer(line, 147, 152),
        "quantity": _integer(line, 152, 170),
        "financial_volume": _decimal(line, 170, 188),
        "quotation_factor": quotation_factor,
        "close_price": close_quote / quotation_factor,
        "isin": isin or None,
        "security_id": f"ISIN:{isin}" if isin else None,
        "distribution_number": _integer(line, 242, 245),
    }


def read_cotahist(path: str | Path) -> pd.DataFrame:
    """Read an annual COTAHIST ZIP into normalized record-01 rows."""
    payload = _zip_payload(path)
    rows: list[dict[str, object]] = []
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        text_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if len(text_members) != 1:
            raise ValueError(f"expected exactly one COTAHIST TXT member, found {text_members}")
        with archive.open(text_members[0]) as raw:
            text = TextIOWrapper(raw, encoding="latin-1", newline="")
            for line_number, line in enumerate(text, start=1):
                record_type = line[0:2]
                if record_type in {"00", "99"}:
                    continue
                if record_type != "01":
                    raise ValueError(
                        f"unexpected COTAHIST record type {record_type!r} at line {line_number}"
                    )
                try:
                    rows.append(parse_cotahist_record(line))
                except ValueError as exc:
                    raise ValueError(f"line {line_number}: {exc}") from exc
    return pd.DataFrame(rows)


def select_regular_share_quotes(df: pd.DataFrame) -> tuple[pd.DataFrame, CotahistAudit]:
    """Select regular spot-market ON/PN share observations without survivorship filtering.

    Distressed/special issuer BDI states are deliberately retained. Rights, receipts,
    funds, options and the fractional-market BDI are excluded by specification/BDI.
    """
    required = {
        "trade_date",
        "bdi_code",
        "ticker",
        "market_type",
        "specification",
        "close_price",
        "isin",
        "security_id",
        "quotation_factor",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing COTAHIST columns: {sorted(missing)}")

    frame = df.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    if frame[["trade_date", "close_price"]].isna().any().any():
        raise ValueError("COTAHIST contains invalid trade_date/close_price")
    if (frame["close_price"] < 0).any():
        raise ValueError("COTAHIST contains negative close price")

    is_share = frame["specification"].str.startswith(("ON", "PN"), na=False)
    selected = frame.loc[
        (frame["market_type"] == 10)
        & frame["bdi_code"].isin(_REGULAR_SHARE_BDI_CODES)
        & is_share
    ].copy()

    missing_isin = int(selected["security_id"].isna().sum())
    canonical = selected.loc[selected["security_id"].notna()].copy()
    duplicate_mask = canonical.duplicated(["trade_date", "security_id"], keep=False)
    duplicate_rows = int(duplicate_mask.sum())
    if duplicate_rows:
        duplicate_sample = canonical.loc[
            duplicate_mask, ["trade_date", "security_id", "ticker", "bdi_code"]
        ].head(10)
        raise ValueError(
            "duplicate canonical security/date observations after regular-share filter: "
            f"{duplicate_sample.to_dict(orient='records')}"
        )

    audit = CotahistAudit(
        rows=len(frame),
        share_rows=len(canonical),
        unique_dates=canonical["trade_date"].nunique(),
        unique_tickers=canonical["ticker"].nunique(),
        unique_isins=canonical["security_id"].nunique(),
        missing_isin_rows=missing_isin,
        duplicate_security_date_rows=duplicate_rows,
    )
    return canonical.reset_index(drop=True), audit

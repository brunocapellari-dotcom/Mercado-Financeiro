from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
import re
import zipfile

import pandas as pd
from lxml import etree


_NS = "{urn:bvmf.100.02.xsd}"
_HEADER_CREATION_RE = re.compile(rb"<CreDtAndTm>([^<]+)</CreDtAndTm>")


def _deepest_zip_bytes(path: str | Path, max_depth: int = 4) -> bytes:
    """Unwrap artifact ZIP layers until a ZIP containing BVBG XML is reached."""
    current = Path(path).read_bytes()
    for _ in range(max_depth):
        with zipfile.ZipFile(BytesIO(current)) as archive:
            names = archive.namelist()
            if any(name.lower().endswith(".xml") for name in names):
                return current
            nested = [name for name in names if name.lower().endswith(".zip")]
            if len(nested) != 1:
                raise ValueError("expected exactly one nested ZIP before BVBG XML layer")
            current = archive.read(nested[0])
    raise ValueError("maximum nested ZIP depth reached before BVBG XML layer")


def _creation_time(archive: zipfile.ZipFile, member: str) -> str:
    with archive.open(member) as stream:
        header = stream.read(16_384)
    match = _HEADER_CREATION_RE.search(header)
    if match is None:
        raise ValueError(f"BVBG.028.02 member lacks CreDtAndTm header: {member}")
    return match.group(1).decode("ascii")


def select_latest_bvbg028_member(path: str | Path) -> tuple[str, str]:
    """Return the latest complete BVBG.028.02 XML member and its creation timestamp.

    A daily B3 instrument package may contain an opening snapshot and a later complete
    snapshot. Research should consume the latest complete file deterministically.
    """
    deep = _deepest_zip_bytes(path)
    with zipfile.ZipFile(BytesIO(deep)) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".xml") and "BVBG.028.02" in name
        ]
        if not candidates:
            raise ValueError("no BVBG.028.02 XML member found")
        ranked = [(_creation_time(archive, name), name) for name in candidates]
    created_at, member = max(ranked)
    return member, created_at


def _text(element: etree._Element, tag: str) -> str | None:
    item = element.find(f".//{_NS}{tag}")
    if item is None or item.text is None:
        return None
    value = item.text.strip()
    return value or None


def _instrument_id(element: etree._Element) -> str | None:
    item = element.find(
        f"./{_NS}FinInstrmId/{_NS}OthrId/{_NS}Id"
    )
    if item is None or item.text is None:
        return None
    value = item.text.strip()
    return value or None


def iter_equity_instruments(path: str | Path) -> Iterator[dict[str, str | None]]:
    """Stream equity-instrument observations from the latest BVBG.028.02 snapshot.

    The XML is deliberately parsed as a stream: a single decompressed daily file can
    exceed 600 MB. The function keeps the B3 value `MktCptlstn` as a raw field because
    historical B3 documentation labels it MarketCapitalisation while current stock
    observations empirically resemble class share counts. No economic interpretation is
    made here without an explicit downstream validation gate.
    """
    deep = _deepest_zip_bytes(path)
    member, package_created_at = select_latest_bvbg028_member(path)

    with zipfile.ZipFile(BytesIO(deep)) as archive, archive.open(member) as stream:
        context = etree.iterparse(
            stream,
            events=("end",),
            tag=f"{_NS}Instrm",
            huge_tree=True,
            recover=False,
        )
        for _, element in context:
            if element.find(f".//{_NS}EqtyInf") is not None:
                yield {
                    "package_created_at": package_created_at,
                    "report_date": _text(element, "Dt"),
                    "activity_indicator": _text(element, "ActvtyInd"),
                    "update_type": _text(element, "UpdTp"),
                    "instrument_id": _instrument_id(element),
                    "market_identifier": _text(element, "MktIdrCd"),
                    "asset": _text(element, "Asst"),
                    "asset_description": _text(element, "AsstDesc"),
                    "market": _text(element, "Mkt"),
                    "segment": _text(element, "Sgmt"),
                    "description": _text(element, "Desc"),
                    "security_category": _text(element, "SctyCtgy"),
                    "isin": _text(element, "ISIN"),
                    "distribution_id": _text(element, "DstrbtnId"),
                    "cfi_code": _text(element, "CFICd"),
                    "specification_code": _text(element, "SpcfctnCd"),
                    "corporation_name": _text(element, "CrpnNm"),
                    "ticker": _text(element, "TckrSymb"),
                    "allocation_round_lot": _text(element, "AllcnRndLot"),
                    "price_factor": _text(element, "PricFctr"),
                    "trading_start_date": _text(element, "TradgStartDt"),
                    "trading_end_date": _text(element, "TradgEndDt"),
                    "corporate_action_start_date": _text(element, "CorpActnStartDt"),
                    "ex_distribution_number": _text(element, "EXDstrbtnNb"),
                    "custody_treatment_type": _text(element, "CtdyTrtmntTp"),
                    "trading_currency": _text(element, "TradgCcy"),
                    "market_capitalisation_raw": _text(element, "MktCptlstn"),
                    "last_price_raw": _text(element, "LastPric"),
                    "first_price_raw": _text(element, "FrstPric"),
                    "days_to_settlement": _text(element, "DaysToSttlm"),
                    "rights_issue_price_raw": _text(element, "RghtsIssePric"),
                }

            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]


def build_cash_security_observations(path: str | Path) -> pd.DataFrame:
    """Build stable observations for regular cash-market shares/fund units.

    The filter uses B3 Market=10 (cash), Segment=1 and ISO-10962 CFI families:
    `ES` ordinary/common shares, `EP` preferred shares, and `C` collective-investment
    instruments. It excludes synthetic TAXA rows that share a reused ISIN but do not
    have an investable equity/fund CFI classification.
    """
    frame = pd.DataFrame(iter_equity_instruments(path))
    if frame.empty:
        return frame

    required = {"report_date", "market", "segment", "ticker", "isin", "cfi_code"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing B3 instrument fields: {sorted(missing)}")

    cfi = frame["cfi_code"].fillna("")
    eligible_cfi = cfi.str.startswith("ES") | cfi.str.startswith("EP") | cfi.str.startswith("C")
    out = frame.loc[
        (frame["market"] == "10")
        & (frame["segment"] == "1")
        & eligible_cfi
        & frame["isin"].notna()
        & frame["ticker"].notna()
    ].copy()

    out["observation_date"] = pd.to_datetime(out["report_date"], errors="coerce")
    if out["observation_date"].isna().any():
        raise ValueError("B3 observation_date contains null or invalid values")

    out["security_id"] = "ISIN:" + out["isin"].astype(str)
    out["listing_id"] = (
        out["security_id"]
        + ":MKT="
        + out["market"].astype(str)
        + ":SGMT="
        + out["segment"].astype(str)
    )

    duplicates = out.duplicated(["observation_date", "listing_id"], keep=False)
    if duplicates.any():
        sample = out.loc[duplicates, ["observation_date", "listing_id", "ticker"]].head(10)
        raise ValueError(f"duplicate canonical listing observations:\n{sample.to_string(index=False)}")

    return out.sort_values(["observation_date", "listing_id"], kind="stable").reset_index(drop=True)

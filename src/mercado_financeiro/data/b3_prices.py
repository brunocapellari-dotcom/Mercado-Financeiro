from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import zipfile

from lxml import etree
import pandas as pd

from mercado_financeiro.security import DownloadPolicy, download_https
from .acquisition import AcquisitionContext
from .historical import HistoricalDataset, VintageMode, require_pit_columns


_PRICE_TAGS: dict[str, tuple[str, ...]] = {
    "ticker": ("TckrSymb",),
    "instrument_id": ("OthrId",),
    "days_to_settlement": ("DaysToSttlm", "DvrsOfSttlm"),
    "trade_quantity": ("TradQty",),
    "financial_volume": ("NtlFinVol",),
    "open_interest": ("OpnIntrst",),
    "instrument_quantity": ("FinInstrmQty",),
    "best_bid": ("BestBidPric",),
    "best_ask": ("BestAskPric",),
    "open_price": ("FrstPric",),
    "low_price": ("MinPric",),
    "high_price": ("MaxPric",),
    "average_price": ("TradAvrgPric",),
    "close_price": ("LastPric",),
    "regular_transactions": ("RglrTxsQty", "RptTxQty", "RptgTxQty"),
}


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _descendant_text(element: etree._Element, aliases: tuple[str, ...]) -> str | None:
    wanted = set(aliases)
    for child in element.iterdescendants():
        if _local_name(child) in wanted and child.text is not None:
            value = child.text.strip()
            if value:
                return value
    return None


def _decimal_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value.replace(",", "."), errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid numeric B3 price value: {value!r}")
    return float(parsed)


def _iter_xml_members(payload: bytes) -> tuple[tuple[str, bytes], ...]:
    if payload[:2] != b"PK":
        return (("payload.xml", payload),)
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = PurePosixPath(info.filename).name
                if name.lower().endswith(".xml"):
                    members.append((name, archive.read(info)))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid B3 price-report ZIP") from exc
    if not members:
        raise ValueError("B3 price-report ZIP contains no XML")
    return tuple(members)


def parse_b3_price_report(payload: bytes) -> pd.DataFrame:
    """Parse BVBG.086.01 or BVBG.186.01 PriceReport XML/ZIP by ISO local-name."""

    if not payload:
        raise ValueError("empty B3 price-report payload")
    records: list[dict[str, object]] = []
    for member_name, xml in _iter_xml_members(payload):
        try:
            context = etree.iterparse(
                BytesIO(xml),
                events=("end",),
                recover=False,
                huge_tree=True,
            )
            for _, element in context:
                if _local_name(element) != "PricRpt":
                    continue
                ticker = _descendant_text(element, _PRICE_TAGS["ticker"])
                if not ticker:
                    element.clear()
                    continue
                trade_date_raw = None
                for child in element.iterdescendants():
                    if _local_name(child) == "TradDt":
                        trade_date_raw = _descendant_text(child, ("Dt",))
                        break
                if not trade_date_raw:
                    raise ValueError(f"missing trade date for {ticker} in {member_name}")
                trade_date = pd.to_datetime(trade_date_raw, errors="coerce", utc=True)
                if pd.isna(trade_date):
                    raise ValueError(f"invalid trade date for {ticker}: {trade_date_raw!r}")
                row: dict[str, object] = {
                    "reference_date": trade_date,
                    "ticker": ticker.upper(),
                    "source_member": member_name,
                }
                row["instrument_id"] = _descendant_text(element, _PRICE_TAGS["instrument_id"])
                for column, aliases in _PRICE_TAGS.items():
                    if column in {"ticker", "instrument_id"}:
                        continue
                    row[column] = _decimal_or_none(_descendant_text(element, aliases))
                records.append(row)
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
        except etree.XMLSyntaxError as exc:
            raise ValueError(f"invalid B3 price-report XML: {member_name}") from exc

    if not records:
        raise ValueError("B3 price-report contains no PriceReport records")
    frame = pd.DataFrame.from_records(records)
    if frame.duplicated(["reference_date", "ticker", "instrument_id"], keep=False).any():
        raise ValueError("duplicate B3 price-report instrument rows")
    return frame.sort_values(
        ["reference_date", "ticker", "instrument_id"], na_position="last"
    ).reset_index(drop=True)


class B3PriceReportSource:
    """Official BVBG.086/.186 collector for a B3-provided file URL.

    URL discovery is deliberately kept outside the parser so an undocumented
    endpoint is never guessed.
    """

    name = "B3_PRICE_REPORT"

    def __init__(
        self,
        *,
        policy: DownloadPolicy | None = None,
        acquisition: AcquisitionContext | None = None,
    ) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"www.b3.com.br", "b3.com.br"}),
            timeout_seconds=60.0,
            max_bytes=2_000_000_000,
        )
        self._acquisition = acquisition or AcquisitionContext()

    def fetch_url(
        self,
        url: str,
        *,
        dataset: str,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        normalized_dataset = dataset.strip().upper()
        if normalized_dataset not in {"BVBG.086.01", "BVBG.186.01"}:
            raise ValueError("dataset must be BVBG.086.01 or BVBG.186.01")
        payload = download_https(url, self._policy)
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        digest = sha256(payload).hexdigest()
        receipt = self._acquisition.preserve(
            payload,
            source_name=normalized_dataset,
            source_url=url,
            retrieved_at=retrieved,
            parser_version="b3-price-report-v1",
            content_type="application/zip",
        )
        frame = parse_b3_price_report(payload)
        frame["available_from"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_retrieved_at"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_sha256"] = digest
        frame["raw_receipt_id"] = receipt
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset=normalized_dataset,
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.EXACT_VINTAGE,
            frame=frame,
        )

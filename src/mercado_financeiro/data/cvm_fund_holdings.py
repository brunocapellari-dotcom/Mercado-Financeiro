from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import re
import sys
import zipfile
from collections.abc import Iterable

import pandas as pd

from mercado_financeiro.security import DownloadPolicy, download_https, validate_zip_bytes
from .historical import HistoricalDataset, VintageMode, require_pit_columns


_BLOCK_RE = re.compile(r"_BLC_(\d+)_", re.IGNORECASE)
_NON_DIGIT = re.compile(r"\D")
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _digits(value: object) -> str:
    return _NON_DIGIT.sub("", str(value or ""))


def _block(member: str) -> str:
    name = member.rsplit("/", 1)[-1]
    match = _BLOCK_RE.search(name)
    if match:
        return f"BLC_{match.group(1)}"
    upper = name.upper()
    if "CONFID" in upper:
        return "FIE_CONFID" if "CDA_FIE" in upper else "CONFID"
    if upper.startswith("CDA_FIE"):
        return "FIE"
    if "_PL_" in upper:
        return "PL"
    return "OTHER"


def _number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"--", "N/D"}:
        return None
    parsed = pd.to_numeric(text.replace(",", "."), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


@dataclass
class _CodedAssetAggregate:
    reference_date: pd.Timestamp
    asset_code: str
    quantity: float = 0.0
    market_value: float = 0.0
    funds: set[str] = field(default_factory=set)


def _first(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


class CVMFundHoldingsSource:
    """PIT-safe streaming reader for CVM fund portfolio-composition (CDA) ZIPs.

    Current monthly CDA files are restated by CVM. Therefore every parsed row is
    available only from retrieval time unless a future exact-vintage archive proves
    an earlier publication timestamp. Detailed holdings may also be withheld under
    confidentiality, so aggregate outputs are explicitly labelled public-detail-only.
    """

    name = "CVM"
    base_url = "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_{year}{month:02d}.zip"

    def __init__(self, *, policy: DownloadPolicy | None = None) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"dados.cvm.gov.br"}),
            timeout_seconds=180.0,
            max_bytes=400_000_000,
        )

    @staticmethod
    def _validated_zip(payload: bytes) -> zipfile.ZipFile:
        validate_zip_bytes(
            payload,
            max_members=40,
            max_total_uncompressed=2_500_000_000,
            max_member_uncompressed=1_000_000_000,
            max_compression_ratio=300.0,
        )
        return zipfile.ZipFile(BytesIO(payload))

    def _download(
        self,
        year: int,
        month: int,
        *,
        retrieved_at: datetime | None,
    ) -> tuple[str, bytes, datetime, str]:
        if year < 2005 or not 1 <= month <= 12:
            raise ValueError("invalid CDA year/month")
        url = self.base_url.format(year=year, month=month)
        payload = download_https(url, self._policy)
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return url, payload, retrieved, sha256(payload).hexdigest()

    @staticmethod
    def _iter_rows(
        archive: zipfile.ZipFile,
        *,
        wanted_blocks: frozenset[str],
    ):
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv") and _block(name) in wanted_blocks
        ]
        if not members:
            raise ValueError(
                "CVM CDA contains none of requested blocks: "
                + ",".join(sorted(wanted_blocks))
            )
        for member in sorted(members):
            block = _block(member)
            with archive.open(member) as raw:
                text = TextIOWrapper(raw, encoding="latin-1", errors="strict", newline="")
                reader = csv.DictReader(text, delimiter=";", quoting=csv.QUOTE_NONE)
                if reader.fieldnames is None:
                    raise ValueError(f"CVM CDA member has no header: {member}")
                required_any = {"CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"}.intersection(reader.fieldnames)
                if not required_any or "DT_COMPTC" not in reader.fieldnames:
                    raise ValueError(f"CVM CDA member schema drift: {member}")
                for row in reader:
                    yield member, block, row

    def fetch_for_funds(
        self,
        year: int,
        month: int,
        *,
        fund_ids: Iterable[str],
        blocks: Iterable[str] = ("BLC_4",),
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        wanted_funds = frozenset(_digits(value) for value in fund_ids if _digits(value))
        if not wanted_funds:
            raise ValueError("fund_ids must contain at least one CNPJ")
        wanted_blocks = frozenset(str(value).strip().upper() for value in blocks if str(value).strip())
        if not wanted_blocks:
            raise ValueError("blocks must not be empty")

        url, payload, retrieved, digest = self._download(year, month, retrieved_at=retrieved_at)
        rows: list[dict[str, object]] = []
        with self._validated_zip(payload) as archive:
            confidential_present = any("CONFID" in name.upper() for name in archive.namelist())
            for member, block, row in self._iter_rows(archive, wanted_blocks=wanted_blocks):
                fund_id = _digits(_first(row, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"))
                if fund_id not in wanted_funds:
                    continue
                reference = pd.to_datetime(row.get("DT_COMPTC"), errors="coerce", utc=True)
                if pd.isna(reference):
                    raise ValueError(f"CVM CDA contains invalid DT_COMPTC in {member}")
                rows.append(
                    {
                        "fund_id": fund_id,
                        "reference_date": reference,
                        "block": block,
                        "application_type": _first(row, "TP_APLIC"),
                        "asset_type": _first(row, "TP_ATIVO"),
                        "asset_code": _first(row, "CD_ATIVO", "DS_ATIVO"),
                        "issuer_name": _first(row, "EMISSOR_LIGADO", "EMISSOR"),
                        "issuer_id": _digits(_first(row, "CNPJ_EMISSOR", "CPF_CNPJ_EMISSOR")) or None,
                        "negotiation_type": _first(row, "TP_NEGOC"),
                        "quantity": _number(row.get("QT_POS_FINAL")),
                        "market_value": _number(
                            _first(row, "VL_MERC_POS_FINAL", "VL_MERCADO", "VL_MERC_POSICAO")
                        ),
                        "source_member": member,
                        "public_detail_only": bool(confidential_present),
                    }
                )

        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(
                columns=[
                    "fund_id",
                    "reference_date",
                    "block",
                    "application_type",
                    "asset_type",
                    "asset_code",
                    "issuer_name",
                    "issuer_id",
                    "negotiation_type",
                    "quantity",
                    "market_value",
                    "source_member",
                    "public_detail_only",
                ]
            )
            frame["reference_date"] = pd.to_datetime(frame["reference_date"], utc=True)

        available = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["available_from"] = available
        frame["source_retrieved_at"] = available
        frame["source_sha256"] = digest
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset=f"FI_CDA_{year}{month:02d}",
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=frame.sort_values(["reference_date", "fund_id", "block", "asset_code"], na_position="last").reset_index(drop=True),
        )

    def fetch_coded_asset_aggregate(
        self,
        year: int,
        month: int,
        *,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        """Aggregate publicly detailed BLC_4 coded-asset holdings without materializing all rows."""

        url, payload, retrieved, digest = self._download(year, month, retrieved_at=retrieved_at)
        aggregate: dict[tuple[pd.Timestamp, str], _CodedAssetAggregate] = {}
        with self._validated_zip(payload) as archive:
            confidential_present = any("CONFID" in name.upper() for name in archive.namelist())
            for _, _, row in self._iter_rows(archive, wanted_blocks=frozenset({"BLC_4"})):
                asset_code = (_first(row, "CD_ATIVO", "DS_ATIVO") or "").strip().upper()
                if not asset_code:
                    continue
                reference = pd.to_datetime(row.get("DT_COMPTC"), errors="coerce", utc=True)
                if pd.isna(reference):
                    raise ValueError("CVM CDA equity row contains invalid DT_COMPTC")
                quantity = _number(row.get("QT_POS_FINAL"))
                market_value = _number(
                    _first(row, "VL_MERC_POS_FINAL", "VL_MERCADO", "VL_MERC_POSICAO")
                )
                if quantity is None and market_value is None:
                    continue
                key = (reference, asset_code)
                item = aggregate.setdefault(
                    key,
                    _CodedAssetAggregate(reference_date=reference, asset_code=asset_code),
                )
                if quantity is not None:
                    item.quantity += quantity
                if market_value is not None:
                    item.market_value += market_value
                fund_id = _digits(_first(row, "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"))
                if fund_id:
                    item.funds.add(fund_id)

        rows = [
            {
                "reference_date": item.reference_date,
                "asset_code": item.asset_code,
                "quantity": item.quantity,
                "market_value": item.market_value,
                "fund_count": len(item.funds),
                "coverage_status": (
                    "public_detail_only_confidential_positions_exist"
                    if confidential_present
                    else "public_detail_only"
                ),
            }
            for item in aggregate.values()
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(
                columns=[
                    "reference_date",
                    "asset_code",
                    "quantity",
                    "market_value",
                    "fund_count",
                    "coverage_status",
                ]
            )
            frame["reference_date"] = pd.to_datetime(frame["reference_date"], utc=True)

        available = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["available_from"] = available
        frame["source_retrieved_at"] = available
        frame["source_sha256"] = digest
        require_pit_columns(frame)
        return HistoricalDataset(
            source=self.name,
            dataset=f"FI_CDA_CODED_ASSET_AGG_{year}{month:02d}",
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=frame.sort_values(["reference_date", "asset_code"]).reset_index(drop=True),
        )

    def healthcheck(self) -> bool:
        return True

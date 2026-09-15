from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import csv
import re
import zipfile

import pandas as pd

from mercado_financeiro.security import validate_zip_bytes
from .b3_emissor import normalize_cnpj

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_ISSUER_CODE_RE = re.compile(r"^[A-Z0-9]{4}$")


@dataclass(frozen=True)
class B3IsinRegistryAudit:
    issuer_rows: int
    valid_issuers: int
    numbering_rows: int
    valid_security_rows: int
    invalid_isin_rows: int
    missing_issuer_rows: int
    ambiguous_isins: int


@dataclass(frozen=True)
class ExactIsinEnrichmentAudit:
    rows: int
    resolved_before: int
    resolved_after: int
    newly_resolved_rows: int
    exact_overrides_prior_conflict_rows: int
    unresolved_rows: int
    ambiguous_registry_rows: int
    mapped_row_ratio: float
    mapped_volume_ratio: float
    unique_issuers: int


def isin_checksum_valid(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    isin = str(value).strip().upper()
    if not _ISIN_RE.fullmatch(isin):
        return False
    expanded = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in isin)
    total = 0
    double = False
    for char in reversed(expanded):
        digit = int(char)
        if double:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double = not double
    return total % 10 == 0


def parse_b3_isin_registry_zip(
    payload: bytes,
    *,
    evidence_available_from: str | pd.Timestamp,
    source_sha256: str | None = None,
) -> tuple[pd.DataFrame, B3IsinRegistryAudit]:
    """Build exact ISIN -> B3 issuer -> CNPJ identity evidence.

    The current B3 ISIN registry is static identity evidence. It may be used to
    reconstruct historical identity, but never to advance publication-time economic
    information. The snapshot availability timestamp and digest are retained.
    """
    validate_zip_bytes(
        payload,
        max_members=20,
        max_total_uncompressed=1_500_000_000,
        max_member_uncompressed=1_200_000_000,
        max_compression_ratio=300.0,
    )
    available = pd.to_datetime(evidence_available_from, errors="coerce", utc=True)
    if pd.isna(available):
        raise ValueError("invalid evidence_available_from")

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = {name.rsplit("/", 1)[-1].upper(): name for name in archive.namelist()}
        if "EMISSOR.TXT" not in names or "NUMERACA.TXT" not in names:
            raise ValueError("B3 ISIN registry requires EMISSOR.TXT and NUMERACA.TXT")

        issuer_rows = 0
        issuers: dict[str, str] = {}
        with archive.open(names["EMISSOR.TXT"]) as raw:
            reader = csv.reader(TextIOWrapper(raw, encoding="latin-1", newline=""))
            for row in reader:
                issuer_rows += 1
                if len(row) < 3:
                    continue
                code = row[0].strip().upper()
                cnpj = normalize_cnpj(row[2])
                if _ISSUER_CODE_RE.fullmatch(code) and cnpj:
                    previous = issuers.get(code)
                    if previous is not None and previous != cnpj:
                        raise ValueError(f"B3 issuer code maps to multiple CNPJs: {code}")
                    issuers[code] = cnpj

        numbering_rows = 0
        invalid_isin_rows = 0
        missing_issuer_rows = 0
        records: list[dict[str, object]] = []
        with archive.open(names["NUMERACA.TXT"]) as raw:
            reader = csv.reader(TextIOWrapper(raw, encoding="latin-1", newline=""))
            for row in reader:
                numbering_rows += 1
                if len(row) < 4:
                    continue
                isin = row[2].strip().upper()
                issuer_code = row[3].strip().upper()
                if not isin_checksum_valid(isin):
                    invalid_isin_rows += 1
                    continue
                issuer_id = issuers.get(issuer_code)
                if issuer_id is None:
                    missing_issuer_rows += 1
                    continue
                records.append(
                    {
                        "security_id": isin,
                        "issuer_id": issuer_id,
                        "issuer_code": issuer_code,
                        "registry_reference_date_raw": row[0].strip(),
                        "cfi_code": row[4].strip() if len(row) > 4 else None,
                        "security_description": row[5].strip() if len(row) > 5 else None,
                        "registry_status": row[42].strip() if len(row) > 42 else None,
                        "numbering_agency": row[44].strip() if len(row) > 44 else None,
                        "identity_evidence_available_from": available,
                        "identity_evidence_source": "B3_ISIN_REGISTRY_CURRENT_SNAPSHOT",
                        "identity_source_sha256": source_sha256,
                    }
                )

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        ambiguous_isins = 0
    else:
        frame = frame.drop_duplicates().reset_index(drop=True)
        counts = frame.groupby("security_id")["issuer_id"].nunique()
        ambiguous = set(counts[counts > 1].index.astype(str))
        ambiguous_isins = len(ambiguous)
        if ambiguous:
            frame["registry_mapping_status"] = frame["security_id"].map(
                lambda value: "ambiguous_registry" if value in ambiguous else "resolved"
            )
        else:
            frame["registry_mapping_status"] = "resolved"
        frame = frame.sort_values(
            ["security_id", "identity_evidence_available_from"], kind="stable"
        ).drop_duplicates(["security_id", "issuer_id"], keep="last")

    audit = B3IsinRegistryAudit(
        issuer_rows=issuer_rows,
        valid_issuers=len(issuers),
        numbering_rows=numbering_rows,
        valid_security_rows=len(frame),
        invalid_isin_rows=invalid_isin_rows,
        missing_issuer_rows=missing_issuer_rows,
        ambiguous_isins=ambiguous_isins,
    )
    return frame, audit


def enrich_historical_identity_with_exact_isin(
    universe: pd.DataFrame,
    registry: pd.DataFrame,
) -> tuple[pd.DataFrame, ExactIsinEnrichmentAudit]:
    required = {
        "security_id",
        "issuer_id",
        "identity_mapping_status",
        "trade_date",
        "financial_volume",
    }
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"missing universe columns: {sorted(missing)}")
    registry_required = {
        "security_id",
        "issuer_id",
        "identity_evidence_available_from",
        "registry_mapping_status",
    }
    missing_registry = registry_required - set(registry.columns)
    if missing_registry:
        raise ValueError(f"missing B3 ISIN registry columns: {sorted(missing_registry)}")

    out = universe.copy()
    out["security_id"] = out["security_id"].astype(str).str.strip().str.upper()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    out["financial_volume"] = pd.to_numeric(out["financial_volume"], errors="coerce")
    if out[["trade_date", "financial_volume"]].isna().any().any():
        raise ValueError("universe contains invalid trade_date/financial_volume")

    evidence = registry.loc[
        registry["registry_mapping_status"].eq("resolved")
    ].copy()
    evidence["identity_evidence_available_from"] = pd.to_datetime(
        evidence["identity_evidence_available_from"], errors="coerce", utc=True
    )
    if evidence["identity_evidence_available_from"].isna().any():
        raise ValueError("registry contains invalid evidence timestamps")
    evidence_counts = evidence.groupby("security_id")["issuer_id"].nunique()
    ambiguous = set(evidence_counts[evidence_counts > 1].index.astype(str))
    evidence = evidence.loc[~evidence["security_id"].isin(ambiguous)]
    evidence = evidence.sort_values(
        ["security_id", "identity_evidence_available_from"], kind="stable"
    ).drop_duplicates("security_id", keep="last")
    evidence = evidence.rename(
        columns={
            "issuer_id": "exact_isin_issuer_id",
            "identity_evidence_available_from": "exact_isin_evidence_available_from",
            "identity_evidence_source": "exact_isin_evidence_source",
            "identity_source_sha256": "exact_isin_source_sha256",
        }
    )
    keep = [
        "security_id",
        "exact_isin_issuer_id",
        "exact_isin_evidence_available_from",
    ]
    for optional in ("exact_isin_evidence_source", "exact_isin_source_sha256"):
        if optional in evidence.columns:
            keep.append(optional)
    out = out.merge(evidence[keep], on="security_id", how="left", validate="many_to_one")

    resolved_before = out["identity_mapping_status"].eq("resolved")
    resolved_before_count = int(resolved_before.sum())
    has_exact = out["exact_isin_issuer_id"].notna()
    prior_conflict = out["identity_mapping_status"].eq("ambiguous_source_conflict")
    disagreement = (
        resolved_before
        & has_exact
        & out["issuer_id"].notna()
        & out["issuer_id"].astype(str).ne(out["exact_isin_issuer_id"].astype(str))
    )
    # Exact official B3 ISIN->issuer evidence is security-specific and therefore
    # outranks ticker/prefix reconstruction for static identity. Preserve the fact
    # that a weaker source disagreed instead of silently losing that information.
    out["identity_weaker_source_disagreed"] = disagreement | prior_conflict
    eligible = has_exact & ~out["security_id"].isin(ambiguous)
    newly_resolved = eligible & ~resolved_before
    out.loc[eligible, "issuer_id"] = out.loc[eligible, "exact_isin_issuer_id"]
    out.loc[eligible, "identity_mapping_status"] = "resolved"
    out.loc[eligible, "identity_policy"] = "historical_identity"
    out.loc[eligible, "identity_resolution_method"] = "B3_ISIN_EXACT"
    out.loc[eligible, "identity_evidence_available_from"] = out.loc[
        eligible, "exact_isin_evidence_available_from"
    ]
    out.loc[eligible, "identity_evidence_source"] = "B3_ISIN_REGISTRY_CURRENT_SNAPSHOT"

    evidence_date = pd.to_datetime(
        out.get("identity_evidence_available_from"), errors="coerce", utc=True
    )
    trade_date_utc = pd.to_datetime(out["trade_date"], errors="coerce", utc=True)
    resolved_after = out["identity_mapping_status"].eq("resolved")
    out["identity_reconstruction_uses_later_evidence"] = (
        resolved_after & evidence_date.notna() & (evidence_date > trade_date_utc)
    )

    total_volume = out["financial_volume"].sum()
    mapped_volume = out.loc[resolved_after, "financial_volume"].sum()
    audit = ExactIsinEnrichmentAudit(
        rows=len(out),
        resolved_before=resolved_before_count,
        resolved_after=int(resolved_after.sum()),
        newly_resolved_rows=int(newly_resolved.sum()),
        exact_overrides_prior_conflict_rows=int((eligible & (disagreement | prior_conflict)).sum()),
        unresolved_rows=int((~resolved_after).sum()),
        ambiguous_registry_rows=int(out["security_id"].isin(ambiguous).sum()),
        mapped_row_ratio=float(resolved_after.mean()) if len(out) else 0.0,
        mapped_volume_ratio=float(mapped_volume / total_volume) if total_volume > 0 else 0.0,
        unique_issuers=out.loc[resolved_after, "issuer_id"].nunique(),
    )
    drop = [
        "exact_isin_issuer_id",
        "exact_isin_evidence_available_from",
        "exact_isin_evidence_source",
        "exact_isin_source_sha256",
    ]
    return out.drop(columns=[column for column in drop if column in out.columns]).reset_index(drop=True), audit

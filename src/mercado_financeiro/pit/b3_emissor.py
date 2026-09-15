from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import csv
from pathlib import PurePosixPath
import re
import zipfile

import pandas as pd

_ISSUER_CODE_RE = re.compile(r"^[A-Z0-9]{4}$")


@dataclass(frozen=True)
class B3EmissorAudit:
    rows: int
    valid_rows: int
    invalid_code_rows: int
    invalid_cnpj_rows: int
    unique_issuer_codes: int
    ambiguous_issuer_codes: int


@dataclass(frozen=True)
class IdentityEnrichmentAudit:
    rows: int
    resolved_before: int
    resolved_after: int
    newly_resolved_rows: int
    conflict_rows: int
    mapped_row_ratio: float
    mapped_volume_ratio: float
    unique_issuers: int


def _cnpj_check_digits(digits12: str) -> str:
    def digit(base: str, weights: list[int]) -> str:
        total = sum(int(ch) * weight for ch, weight in zip(base, weights, strict=True))
        remainder = total % 11
        value = 0 if remainder < 2 else 11 - remainder
        return str(value)

    d1 = digit(digits12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digit(digits12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return d1 + d2


def normalize_cnpj(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 14 or len(set(digits)) == 1:
        return None
    if _cnpj_check_digits(digits[:12]) != digits[-2:]:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def ticker_issuer_code(ticker: object) -> str | None:
    if ticker is None or pd.isna(ticker):
        return None
    text = str(ticker).strip().upper().replace(" ", "")
    if len(text) < 5:
        return None
    code = text[:4]
    return code if _ISSUER_CODE_RE.fullmatch(code) else None


def parse_b3_emissor_zip(
    payload: bytes,
    *,
    evidence_available_from: str | pd.Timestamp,
    source_sha256: str | None = None,
) -> tuple[pd.DataFrame, B3EmissorAudit]:
    """Parse B3 EMISSOR.TXT as static issuer-identity evidence.

    EMISSOR is not used as publication-time economic data. Its current snapshot may
    reconstruct historical static identity only, and its evidence timestamp is kept
    so every ex-post mapping remains auditable.
    """
    if not payload:
        raise ValueError("empty B3 EMISSOR ZIP payload")
    available = pd.Timestamp(evidence_available_from)
    if pd.isna(available):
        raise ValueError("invalid evidence_available_from")

    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid B3 EMISSOR ZIP") from exc

    with archive:
        candidates = []
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe member path in B3 EMISSOR ZIP")
            if path.name.upper() == "EMISSOR.TXT":
                candidates.append(info)
        if len(candidates) != 1:
            raise ValueError(f"expected exactly one EMISSOR.TXT, found {len(candidates)}")
        with archive.open(candidates[0]) as raw:
            wrapper = TextIOWrapper(raw, encoding="latin-1", newline="")
            rows = list(csv.reader(wrapper))

    records: list[dict[str, object]] = []
    invalid_code = 0
    invalid_cnpj = 0
    for row in rows:
        if len(row) < 3:
            continue
        code = row[0].strip().upper()
        if not _ISSUER_CODE_RE.fullmatch(code):
            invalid_code += 1
            continue
        cnpj = normalize_cnpj(row[2])
        if cnpj is None:
            invalid_cnpj += 1
            continue
        records.append(
            {
                "issuer_code": code,
                "issuer_id": cnpj,
                "issuer_name": row[1].strip(),
                "upstream_date_raw": row[3].strip() if len(row) > 3 else None,
                "identity_evidence_available_from": available,
                "identity_evidence_source": "B3_EMISSOR_CURRENT_SNAPSHOT",
                "identity_source_sha256": source_sha256,
            }
        )

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "issuer_code",
                "issuer_id",
                "issuer_name",
                "upstream_date_raw",
                "identity_evidence_available_from",
                "identity_evidence_source",
                "identity_source_sha256",
            ]
        )
        ambiguous_codes = 0
        unique_codes = 0
    else:
        frame = frame.drop_duplicates().reset_index(drop=True)
        counts = frame.groupby("issuer_code")["issuer_id"].nunique()
        ambiguous_codes = int((counts > 1).sum())
        unique_codes = int(counts.size)

    audit = B3EmissorAudit(
        rows=len(rows),
        valid_rows=len(frame),
        invalid_code_rows=invalid_code,
        invalid_cnpj_rows=invalid_cnpj,
        unique_issuer_codes=unique_codes,
        ambiguous_issuer_codes=ambiguous_codes,
    )
    return frame, audit


def resolve_b3_emissor_identity(
    tickers: pd.Series,
    emissor: pd.DataFrame,
) -> pd.DataFrame:
    required = {"issuer_code", "issuer_id", "identity_evidence_available_from"}
    missing = required - set(emissor.columns)
    if missing:
        raise ValueError(f"missing B3 EMISSOR columns: {sorted(missing)}")

    evidence = emissor.copy()
    counts = evidence.groupby("issuer_code")["issuer_id"].nunique()
    ambiguous = set(counts[counts > 1].index.astype(str))
    evidence = evidence.sort_values(
        ["issuer_code", "identity_evidence_available_from"], kind="stable"
    ).drop_duplicates(["issuer_code", "issuer_id"], keep="last")

    input_frame = pd.DataFrame({"ticker": tickers.astype(str)})
    input_frame["issuer_code"] = input_frame["ticker"].map(ticker_issuer_code)
    out = input_frame.merge(evidence, on="issuer_code", how="left", validate="many_to_many")

    duplicated_ticker = out.groupby("ticker")["issuer_id"].nunique(dropna=True)
    ambiguous_tickers = set(duplicated_ticker[duplicated_ticker > 1].index.astype(str))
    out["identity_mapping_status"] = "unresolved_no_b3_emissor_evidence"
    resolved_mask = out["issuer_id"].notna()
    out.loc[resolved_mask, "identity_mapping_status"] = "resolved"
    out.loc[
        out["issuer_code"].isin(ambiguous) | out["ticker"].isin(ambiguous_tickers),
        "identity_mapping_status",
    ] = "ambiguous_issuer"
    out.loc[out["identity_mapping_status"] != "resolved", "issuer_id"] = pd.NA
    out = out.sort_values(["ticker", "identity_evidence_available_from"], kind="stable")
    out = out.drop_duplicates("ticker", keep="last")
    return out.reset_index(drop=True)


def enrich_historical_identity_with_b3_emissor(
    universe: pd.DataFrame,
    emissor: pd.DataFrame,
) -> tuple[pd.DataFrame, IdentityEnrichmentAudit]:
    """Fill unresolved historical issuer identities from deterministic B3 evidence.

    Existing resolved FCA mappings are never silently overwritten. If B3 and FCA
    disagree on a resolved issuer, the row fails closed as a source conflict. B3
    EMISSOR evidence is allowed only for static historical identity reconstruction;
    it does not change publication-time eligibility of fundamentals or share counts.
    """
    required = {
        "ticker",
        "issuer_id",
        "identity_mapping_status",
        "trade_date",
        "financial_volume",
        "security_id",
    }
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"missing universe columns: {sorted(missing)}")

    out = universe.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    out["financial_volume"] = pd.to_numeric(out["financial_volume"], errors="coerce")
    if out[["trade_date", "financial_volume"]].isna().any().any():
        raise ValueError("universe contains invalid trade_date/financial_volume")

    resolved_before_mask = out["identity_mapping_status"].eq("resolved")
    resolved_before = int(resolved_before_mask.sum())

    evidence = resolve_b3_emissor_identity(out["ticker"].drop_duplicates(), emissor).rename(
        columns={
            "issuer_id": "b3_emissor_issuer_id",
            "identity_mapping_status": "b3_emissor_mapping_status",
            "identity_evidence_available_from": "b3_emissor_evidence_available_from",
            "identity_evidence_source": "b3_emissor_evidence_source",
        }
    )
    keep = [
        "ticker",
        "b3_emissor_issuer_id",
        "b3_emissor_mapping_status",
        "b3_emissor_evidence_available_from",
    ]
    if "b3_emissor_evidence_source" in evidence.columns:
        keep.append("b3_emissor_evidence_source")
    evidence = evidence[keep]
    out = out.merge(evidence, on="ticker", how="left", validate="many_to_one")

    b3_resolved = out["b3_emissor_mapping_status"].eq("resolved")
    conflict = (
        resolved_before_mask
        & b3_resolved
        & out["issuer_id"].notna()
        & out["b3_emissor_issuer_id"].notna()
        & out["issuer_id"].astype(str).ne(out["b3_emissor_issuer_id"].astype(str))
    )
    if conflict.any():
        out.loc[conflict, "identity_mapping_status"] = "ambiguous_source_conflict"
        out.loc[conflict, "issuer_id"] = pd.NA

    unresolved = out["identity_mapping_status"].astype(str).str.startswith("unresolved")
    fill = unresolved & b3_resolved
    out.loc[fill, "issuer_id"] = out.loc[fill, "b3_emissor_issuer_id"]
    out.loc[fill, "identity_mapping_status"] = "resolved"
    out.loc[fill, "identity_evidence_available_from"] = out.loc[
        fill, "b3_emissor_evidence_available_from"
    ]
    out.loc[fill, "identity_evidence_reference_date"] = pd.NaT
    out.loc[fill, "identity_policy"] = "historical_identity"
    out.loc[fill, "identity_resolution_method"] = "B3_EMISSOR_PREFIX4"
    out.loc[fill, "identity_evidence_source"] = "B3_EMISSOR_CURRENT_SNAPSHOT"

    evidence_date = pd.to_datetime(out.get("identity_evidence_available_from"), errors="coerce")
    resolved_after_mask = out["identity_mapping_status"].eq("resolved")
    out["identity_reconstruction_uses_later_evidence"] = (
        resolved_after_mask & evidence_date.notna() & (evidence_date > out["trade_date"])
    )

    mapped_volume = out.loc[resolved_after_mask, "financial_volume"].sum()
    total_volume = out["financial_volume"].sum()
    audit = IdentityEnrichmentAudit(
        rows=len(out),
        resolved_before=resolved_before,
        resolved_after=int(resolved_after_mask.sum()),
        newly_resolved_rows=int(fill.sum()),
        conflict_rows=int(conflict.sum()),
        mapped_row_ratio=float(resolved_after_mask.mean()) if len(out) else 0.0,
        mapped_volume_ratio=float(mapped_volume / total_volume) if total_volume > 0 else 0.0,
        unique_issuers=out.loc[resolved_after_mask, "issuer_id"].nunique(),
    )
    drop_cols = [
        "b3_emissor_issuer_id",
        "b3_emissor_mapping_status",
        "b3_emissor_evidence_available_from",
        "b3_emissor_evidence_source",
    ]
    return out.drop(columns=[c for c in drop_cols if c in out.columns]).reset_index(drop=True), audit

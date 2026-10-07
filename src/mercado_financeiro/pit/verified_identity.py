from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import pandas as pd

from .b3_emissor import normalize_cnpj


@dataclass(frozen=True)
class VerifiedIdentityEnrichmentAudit:
    rows: int
    evidence_rows: int
    resolved_before: int
    resolved_after: int
    newly_resolved_rows: int
    disagreement_rows: int
    mapped_row_ratio: float
    mapped_volume_ratio: float
    unique_issuers: int


# Manual evidence is deliberately tiny and explicit. It is allowed only when a
# material historical identity remains unresolved after the automatic B3/CVM
# hierarchy and primary-source documents jointly establish the security -> legal
# issuer bridge. These rows contain static identity only; no economic field is
# carried from later evidence into an earlier backtest date.
_VERIFIED_IDENTITY_ROWS: tuple[dict[str, object], ...] = (
    {
        "security_id": "ISIN:BRALLLACNOR6",
        "ticker": "ALLL3",
        "issuer_short_name": "ALL AMER LAT",
        "issuer_id": "02.387.241/0001-60",
        "cvm_code": "17450",
        "evidence_reference_date": "2014-12-31",
        # The ticker/company document was received by CVM in 2015. Using the
        # later of the two source dates is conservative even though the legal
        # identity source itself dates from 2006.
        "evidence_available_from": "2015-03-25T00:00:00Z",
        "ticker_evidence_url": (
            "https://sistemas.cvm.gov.br/docsrecebidos/"
            "20150325162433UP3a52097a963b4b9a9919a7f5ebd327bc.pdf"
        ),
        "issuer_evidence_url": (
            "https://sistemas.cvm.gov.br/dados/LaudEditOpa/RJ-2006-06091/"
            "20061026_EDITAL_DE_OFERTA_PUBLICA.pdf"
        ),
        "evidence_source": "CVM_PRIMARY_DOCUMENT_PAIR",
    },
)


def _official_cvm_url(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    parsed = urlparse(str(value))
    return parsed.scheme == "https" and parsed.hostname == "sistemas.cvm.gov.br"


def verified_historical_identity_evidence() -> pd.DataFrame:
    """Return the audited primary-source exception registry.

    The registry is intentionally code-reviewed rather than loaded from an opaque
    external mapping. Every row must identify one exact COTAHIST security/ticker/name
    tuple and a valid issuer CNPJ, with two official CVM source links: one tying the
    historical ticker to the company and another tying that legal company to CNPJ/CVM
    identity. Duplicate security/ticker/name keys are forbidden.
    """
    frame = pd.DataFrame.from_records(_VERIFIED_IDENTITY_ROWS)
    required = {
        "security_id",
        "ticker",
        "issuer_short_name",
        "issuer_id",
        "cvm_code",
        "evidence_reference_date",
        "evidence_available_from",
        "ticker_evidence_url",
        "issuer_evidence_url",
        "evidence_source",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"verified identity registry missing columns: {sorted(missing)}")

    frame["security_id"] = frame["security_id"].astype(str).str.strip().str.upper()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["issuer_short_name"] = frame["issuer_short_name"].astype(str).str.strip().str.upper()
    frame["issuer_id"] = frame["issuer_id"].map(normalize_cnpj)
    if frame["issuer_id"].isna().any():
        raise ValueError("verified identity registry contains invalid issuer CNPJ")
    if frame.duplicated(["security_id", "ticker", "issuer_short_name"], keep=False).any():
        raise ValueError("verified identity registry contains duplicate exact security keys")
    if not frame["security_id"].str.startswith("ISIN:").all():
        raise ValueError("verified identity registry security_id must be canonical ISIN keys")
    if not frame["ticker_evidence_url"].map(_official_cvm_url).all():
        raise ValueError("verified identity ticker evidence must use official CVM HTTPS URLs")
    if not frame["issuer_evidence_url"].map(_official_cvm_url).all():
        raise ValueError("verified identity issuer evidence must use official CVM HTTPS URLs")

    frame["evidence_available_from"] = pd.to_datetime(
        frame["evidence_available_from"], errors="coerce", utc=True
    )
    frame["evidence_reference_date"] = pd.to_datetime(
        frame["evidence_reference_date"], errors="coerce"
    )
    if frame[["evidence_available_from", "evidence_reference_date"]].isna().any().any():
        raise ValueError("verified identity registry contains invalid evidence dates")
    return frame


def enrich_historical_identity_with_verified_evidence(
    universe: pd.DataFrame,
    evidence: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, VerifiedIdentityEnrichmentAudit]:
    """Fill unresolved identity only from exact, reviewed primary-source evidence.

    Stronger automatic mappings are never overwritten. If reviewed evidence disagrees
    with an already-resolved issuer, the row is flagged for audit and the existing
    stronger mapping remains authoritative.
    """
    required = {
        "security_id",
        "ticker",
        "issuer_short_name",
        "issuer_id",
        "identity_mapping_status",
        "trade_date",
        "financial_volume",
    }
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"missing universe columns for verified identity: {sorted(missing)}")

    evidence = verified_historical_identity_evidence() if evidence is None else evidence.copy()
    evidence_required = {
        "security_id",
        "ticker",
        "issuer_short_name",
        "issuer_id",
        "cvm_code",
        "evidence_reference_date",
        "evidence_available_from",
        "ticker_evidence_url",
        "issuer_evidence_url",
        "evidence_source",
    }
    evidence_missing = evidence_required - set(evidence.columns)
    if evidence_missing:
        raise ValueError(f"verified evidence missing columns: {sorted(evidence_missing)}")
    evidence["issuer_id"] = evidence["issuer_id"].map(normalize_cnpj)
    if evidence["issuer_id"].isna().any():
        raise ValueError("verified evidence contains invalid issuer CNPJ")
    if evidence.duplicated(["security_id", "ticker", "issuer_short_name"], keep=False).any():
        raise ValueError("verified evidence contains duplicate exact keys")
    evidence["evidence_available_from"] = pd.to_datetime(
        evidence["evidence_available_from"], errors="coerce", utc=True
    )
    evidence["evidence_reference_date"] = pd.to_datetime(
        evidence["evidence_reference_date"], errors="coerce"
    )
    if evidence[["evidence_available_from", "evidence_reference_date"]].isna().any().any():
        raise ValueError("verified evidence contains invalid dates")

    out = universe.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    out["financial_volume"] = pd.to_numeric(out["financial_volume"], errors="coerce")
    if out[["trade_date", "financial_volume"]].isna().any().any():
        raise ValueError("universe contains invalid trade date or financial volume")

    if "identity_evidence_available_from" in out.columns:
        out["identity_evidence_available_from"] = pd.to_datetime(
            out["identity_evidence_available_from"], errors="coerce", utc=True
        )
    else:
        out["identity_evidence_available_from"] = pd.Series(
            pd.NaT, index=out.index, dtype="datetime64[ns, UTC]"
        )

    evidence = evidence.rename(
        columns={
            "issuer_id": "verified_issuer_id",
            "cvm_code": "verified_cvm_code",
            "evidence_reference_date": "verified_reference_date",
            "evidence_available_from": "verified_available_from",
            "ticker_evidence_url": "verified_ticker_evidence_url",
            "issuer_evidence_url": "verified_issuer_evidence_url",
            "evidence_source": "verified_evidence_source",
        }
    )
    out = out.merge(
        evidence,
        on=["security_id", "ticker", "issuer_short_name"],
        how="left",
        validate="many_to_one",
    )

    resolved_before_mask = out["identity_mapping_status"].eq("resolved")
    resolved_before = int(resolved_before_mask.sum())
    matched = out["verified_issuer_id"].notna()
    disagreement = (
        resolved_before_mask
        & matched
        & out["issuer_id"].notna()
        & out["issuer_id"].astype(str).ne(out["verified_issuer_id"].astype(str))
    )
    prior_disagreement = out.get(
        "identity_weaker_source_disagreed", pd.Series(False, index=out.index)
    ).fillna(False).astype(bool)
    out["identity_weaker_source_disagreed"] = prior_disagreement | disagreement

    unresolved = out["identity_mapping_status"].astype(str).str.startswith("unresolved")
    fill = unresolved & matched
    out.loc[fill, "issuer_id"] = out.loc[fill, "verified_issuer_id"]
    out.loc[fill, "identity_mapping_status"] = "resolved"
    out.loc[fill, "identity_policy"] = "historical_identity"
    out.loc[fill, "identity_resolution_method"] = "CVM_PRIMARY_SOURCE_VERIFIED_SECURITY"
    out.loc[fill, "identity_evidence_source"] = out.loc[fill, "verified_evidence_source"]
    out.loc[fill, "identity_evidence_available_from"] = out.loc[
        fill, "verified_available_from"
    ]
    out.loc[fill, "identity_evidence_reference_date"] = out.loc[
        fill, "verified_reference_date"
    ]
    out.loc[fill, "identity_evidence_cvm_code"] = out.loc[fill, "verified_cvm_code"]
    out.loc[fill, "identity_evidence_ticker_url"] = out.loc[
        fill, "verified_ticker_evidence_url"
    ]
    out.loc[fill, "identity_evidence_issuer_url"] = out.loc[
        fill, "verified_issuer_evidence_url"
    ]

    evidence_date = pd.to_datetime(
        out.get("identity_evidence_available_from"), errors="coerce", utc=True
    )
    trade_date = pd.to_datetime(out["trade_date"], errors="coerce", utc=True)
    resolved_after_mask = out["identity_mapping_status"].eq("resolved")
    out["identity_reconstruction_uses_later_evidence"] = (
        resolved_after_mask & evidence_date.notna() & (evidence_date > trade_date)
    )

    total_volume = float(out["financial_volume"].sum())
    mapped_volume = float(out.loc[resolved_after_mask, "financial_volume"].sum())
    audit = VerifiedIdentityEnrichmentAudit(
        rows=len(out),
        evidence_rows=len(evidence),
        resolved_before=resolved_before,
        resolved_after=int(resolved_after_mask.sum()),
        newly_resolved_rows=int(fill.sum()),
        disagreement_rows=int(disagreement.sum()),
        mapped_row_ratio=float(resolved_after_mask.mean()) if len(out) else 0.0,
        mapped_volume_ratio=float(mapped_volume / total_volume) if total_volume > 0 else 0.0,
        unique_issuers=int(out.loc[resolved_after_mask, "issuer_id"].nunique()),
    )

    helper_columns = [
        "verified_issuer_id",
        "verified_cvm_code",
        "verified_reference_date",
        "verified_available_from",
        "verified_ticker_evidence_url",
        "verified_issuer_evidence_url",
        "verified_evidence_source",
    ]
    return out.drop(columns=[column for column in helper_columns if column in out.columns]).reset_index(drop=True), audit

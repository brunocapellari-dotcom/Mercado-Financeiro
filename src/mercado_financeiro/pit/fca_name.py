from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import pandas as pd

from .b3_emissor import normalize_cnpj
from .cvm import _inner_zip_bytes, _read_csv

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_STOPWORDS = {
    "A",
    "CIA",
    "COMPANHIA",
    "DA",
    "DAS",
    "DE",
    "DO",
    "DOS",
    "E",
    "EM",
    "HOLDING",
    "HOLDINGS",
    "LTDA",
    "PARTICIPACAO",
    "PARTICIPACOES",
    "S",
    "SA",
}


@dataclass(frozen=True)
class FCAIssuerNameAudit:
    year: int
    section_rows: int
    name_rows: int
    unique_issuers: int
    unique_names: int
    missing_available_from: int


@dataclass(frozen=True)
class FCANameEnrichmentAudit:
    rows: int
    resolved_before: int
    resolved_after: int
    newly_resolved_rows: int
    disagreement_rows: int
    ambiguous_short_names: int
    mapped_row_ratio: float
    mapped_volume_ratio: float
    unique_issuers: int


def normalize_company_name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    text = _NON_ALNUM_RE.sub(" ", text.upper()).strip()
    if not text:
        return None
    tokens = [token for token in text.split() if token not in _STOPWORDS]
    return " ".join(tokens) or None


def _tokens(value: object) -> tuple[str, ...]:
    normalized = normalize_company_name(value)
    return tuple(normalized.split()) if normalized else ()


def _acronyms(tokens: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for width in range(2, min(5, len(tokens) + 1)):
        for start in range(0, len(tokens) - width + 1):
            chunk = tokens[start : start + width]
            if all(chunk):
                out.add("".join(token[0] for token in chunk))
    return out


def _token_matches(short: str, full_tokens: tuple[str, ...], acronyms: set[str]) -> bool:
    if not short:
        return False
    if short in full_tokens:
        return True
    if len(short) <= 2:
        return short in acronyms
    for full in full_tokens:
        if len(full) >= 3 and (full.startswith(short) or short.startswith(full)):
            return True
    return False


def _name_matches(short_name: object, full_name: object) -> bool:
    short_tokens = _tokens(short_name)
    full_tokens = _tokens(full_name)
    if not short_tokens or not full_tokens:
        return False
    acronyms = _acronyms(full_tokens)
    matches = [_token_matches(token, full_tokens, acronyms) for token in short_tokens]
    if not all(matches):
        return False
    # One-token aliases are accepted only when they are reasonably distinctive;
    # uniqueness across issuer ids is enforced by the resolver below.
    if len(short_tokens) == 1:
        return len(short_tokens[0]) >= 4
    # Require enough literal information to avoid promoting tiny abbreviation pairs.
    informative = sum(len(token) for token in short_tokens if len(token) >= 3)
    return informative >= 6


def audit_fca_issuer_name_registry(
    path: str | Path,
    year: int,
) -> tuple[pd.DataFrame, FCAIssuerNameAudit]:
    """Build issuer-name aliases from the represented FCA filing version.

    The bridge is identity metadata only. Every alias is tied to the exact FCA
    filing ledger row so evidence availability remains auditable. It may be used
    ex-post only by the explicit ``historical_identity`` reconstruction path.
    """
    inner = _inner_zip_bytes(path)
    ledger = _read_csv(inner, f"fca_cia_aberta_{year}.csv")
    general = _read_csv(inner, f"fca_cia_aberta_geral_{year}.csv")

    required_ledger = {"CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC", "DT_RECEB"}
    required_general = {
        "CNPJ_Companhia",
        "Data_Referencia",
        "Versao",
        "ID_Documento",
        "Nome_Empresarial",
    }
    missing_ledger = required_ledger - set(ledger.columns)
    missing_general = required_general - set(general.columns)
    if missing_ledger:
        raise ValueError(f"FCA {year}: missing ledger columns {sorted(missing_ledger)}")
    if missing_general:
        raise ValueError(f"FCA {year}: missing general columns {sorted(missing_general)}")

    ledger_cols = list(required_ledger)
    if "DENOM_CIA" in ledger.columns:
        ledger_cols.append("DENOM_CIA")
    ledger = ledger[ledger_cols].copy()
    ledger["DT_RECEB"] = pd.to_datetime(ledger["DT_RECEB"], errors="coerce")
    if ledger["DT_RECEB"].isna().any():
        raise ValueError(f"FCA {year}: invalid DT_RECEB in filing ledger")
    if ledger.duplicated(["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"], keep=False).any():
        raise ValueError(f"FCA {year}: duplicate submission ledger keys")

    joined = general.merge(
        ledger,
        left_on=["CNPJ_Companhia", "Data_Referencia", "Versao", "ID_Documento"],
        right_on=["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"],
        how="left",
        validate="many_to_one",
    ).rename(columns={"DT_RECEB": "available_from"})
    missing_available = int(joined["available_from"].isna().sum())
    if missing_available:
        raise ValueError(f"FCA {year}: {missing_available} general rows lack available_from")

    rows: list[dict[str, object]] = []
    name_columns: list[tuple[str, str]] = [("Nome_Empresarial", "current_name")]
    if "Nome_Empresarial_Anterior" in joined.columns:
        name_columns.append(("Nome_Empresarial_Anterior", "previous_name"))
    if "DENOM_CIA" in joined.columns:
        name_columns.append(("DENOM_CIA", "ledger_name"))

    for row in joined.itertuples(index=False):
        payload = row._asdict()
        issuer_id = normalize_cnpj(payload.get("CNPJ_Companhia"))
        if issuer_id is None:
            raise ValueError(f"FCA {year}: invalid issuer CNPJ in general section")
        reference_date = pd.to_datetime(payload.get("Data_Referencia"), errors="coerce")
        available_from = pd.to_datetime(payload.get("available_from"), errors="coerce", utc=True)
        if pd.isna(reference_date) or pd.isna(available_from):
            raise ValueError(f"FCA {year}: invalid issuer-name evidence dates")
        for column, name_kind in name_columns:
            raw_name = payload.get(column)
            normalized = normalize_company_name(raw_name)
            if not normalized:
                continue
            rows.append(
                {
                    "issuer_id": issuer_id,
                    "company_name": str(raw_name).strip(),
                    "company_name_normalized": normalized,
                    "name_kind": name_kind,
                    "reference_date": reference_date,
                    "available_from": available_from,
                    "evidence_document_id": payload.get("ID_Documento"),
                    "evidence_version": payload.get("Versao"),
                    "source": "CVM_FCA_GERAL_NAME",
                    "vintage_mode": "conservative_latest_snapshot",
                }
            )

    frame = pd.DataFrame.from_records(rows)
    if not frame.empty:
        frame = frame.drop_duplicates(
            [
                "issuer_id",
                "company_name_normalized",
                "reference_date",
                "available_from",
                "evidence_document_id",
            ],
            keep="last",
        ).sort_values(
            ["company_name_normalized", "reference_date", "available_from"], kind="stable"
        ).reset_index(drop=True)

    audit = FCAIssuerNameAudit(
        year=year,
        section_rows=len(general),
        name_rows=len(frame),
        unique_issuers=frame["issuer_id"].nunique() if not frame.empty else 0,
        unique_names=frame["company_name_normalized"].nunique() if not frame.empty else 0,
        missing_available_from=missing_available,
    )
    return frame, audit


def combine_fca_issuer_name_history(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    required = {
        "issuer_id",
        "company_name",
        "company_name_normalized",
        "reference_date",
        "available_from",
    }
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"missing FCA issuer-name columns: {sorted(missing)}")
    return out.drop_duplicates(
        [
            "issuer_id",
            "company_name_normalized",
            "reference_date",
            "available_from",
            "evidence_document_id",
        ],
        keep="last",
    ).sort_values(
        ["company_name_normalized", "reference_date", "available_from"], kind="stable"
    ).reset_index(drop=True)


def resolve_fca_name_identity(
    short_names: pd.Series,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "issuer_id",
        "company_name",
        "company_name_normalized",
        "reference_date",
        "available_from",
    }
    missing = required - set(registry.columns)
    if missing:
        raise ValueError(f"missing FCA issuer-name registry columns: {sorted(missing)}")

    evidence = registry.copy()
    evidence["available_from"] = pd.to_datetime(evidence["available_from"], errors="coerce", utc=True)
    evidence["reference_date"] = pd.to_datetime(evidence["reference_date"], errors="coerce")
    if evidence[["available_from", "reference_date"]].isna().any().any():
        raise ValueError("FCA issuer-name registry contains invalid evidence dates")
    unique_evidence = evidence.drop_duplicates(
        ["issuer_id", "company_name_normalized"], keep="first"
    ).reset_index(drop=True)

    results: list[dict[str, object]] = []
    for short_name in short_names.dropna().astype(str).drop_duplicates():
        candidates = unique_evidence.loc[
            unique_evidence["company_name_normalized"].map(
                lambda full: _name_matches(short_name, full)
            )
        ].copy()
        issuer_ids = sorted(candidates["issuer_id"].dropna().astype(str).unique())
        if len(issuer_ids) == 1:
            chosen = candidates.loc[candidates["issuer_id"].astype(str).eq(issuer_ids[0])].sort_values(
                ["available_from", "reference_date"], kind="stable"
            ).iloc[0]
            results.append(
                {
                    "issuer_short_name": short_name,
                    "fca_name_issuer_id": issuer_ids[0],
                    "fca_name_mapping_status": "resolved",
                    "fca_name_matched_name": chosen["company_name"],
                    "fca_name_evidence_available_from": chosen["available_from"],
                    "fca_name_evidence_reference_date": chosen["reference_date"],
                    "fca_name_candidate_issuers": 1,
                }
            )
        elif len(issuer_ids) > 1:
            results.append(
                {
                    "issuer_short_name": short_name,
                    "fca_name_issuer_id": pd.NA,
                    "fca_name_mapping_status": "ambiguous_name_evidence",
                    "fca_name_matched_name": pd.NA,
                    "fca_name_evidence_available_from": pd.NaT,
                    "fca_name_evidence_reference_date": pd.NaT,
                    "fca_name_candidate_issuers": len(issuer_ids),
                }
            )
        else:
            results.append(
                {
                    "issuer_short_name": short_name,
                    "fca_name_issuer_id": pd.NA,
                    "fca_name_mapping_status": "unresolved_no_name_evidence",
                    "fca_name_matched_name": pd.NA,
                    "fca_name_evidence_available_from": pd.NaT,
                    "fca_name_evidence_reference_date": pd.NaT,
                    "fca_name_candidate_issuers": 0,
                }
            )
    return pd.DataFrame.from_records(results)


def enrich_historical_identity_with_fca_names(
    universe: pd.DataFrame,
    registry: pd.DataFrame,
) -> tuple[pd.DataFrame, FCANameEnrichmentAudit]:
    """Fill unresolved static identity from unique B3-short-name -> CVM-name matches.

    This resolver is deliberately weaker than direct ticker or exact security evidence:
    it only fills unresolved rows and never overwrites an existing resolved issuer.
    Ambiguous names are recorded but are not promoted into the canonical identity.
    """
    required = {
        "issuer_short_name",
        "issuer_id",
        "identity_mapping_status",
        "trade_date",
        "financial_volume",
    }
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"missing universe columns for FCA name enrichment: {sorted(missing)}")

    out = universe.copy()
    out["financial_volume"] = pd.to_numeric(out["financial_volume"], errors="coerce")
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    if out[["financial_volume", "trade_date"]].isna().any().any():
        raise ValueError("invalid universe values for FCA name enrichment")

    resolved_before_mask = out["identity_mapping_status"].eq("resolved")
    resolved_before = int(resolved_before_mask.sum())
    mapping = resolve_fca_name_identity(out["issuer_short_name"], registry)
    if mapping.empty:
        mapped_volume = out.loc[resolved_before_mask, "financial_volume"].sum()
        total_volume = out["financial_volume"].sum()
        return out, FCANameEnrichmentAudit(
            rows=len(out),
            resolved_before=resolved_before,
            resolved_after=resolved_before,
            newly_resolved_rows=0,
            disagreement_rows=0,
            ambiguous_short_names=0,
            mapped_row_ratio=float(resolved_before_mask.mean()) if len(out) else 0.0,
            mapped_volume_ratio=float(mapped_volume / total_volume) if total_volume > 0 else 0.0,
            unique_issuers=out.loc[resolved_before_mask, "issuer_id"].nunique(),
        )

    out = out.merge(mapping, on="issuer_short_name", how="left", validate="many_to_one")
    name_resolved = out["fca_name_mapping_status"].eq("resolved")
    disagreement = (
        resolved_before_mask
        & name_resolved
        & out["issuer_id"].notna()
        & out["fca_name_issuer_id"].notna()
        & out["issuer_id"].astype(str).ne(out["fca_name_issuer_id"].astype(str))
    )
    prior_disagreement = out.get(
        "identity_weaker_source_disagreed", pd.Series(False, index=out.index)
    ).fillna(False).astype(bool)
    out["identity_weaker_source_disagreed"] = prior_disagreement | disagreement

    unresolved = out["identity_mapping_status"].astype(str).str.startswith("unresolved")
    fill = unresolved & name_resolved
    out.loc[fill, "issuer_id"] = out.loc[fill, "fca_name_issuer_id"]
    out.loc[fill, "identity_mapping_status"] = "resolved"
    out.loc[fill, "identity_evidence_available_from"] = out.loc[
        fill, "fca_name_evidence_available_from"
    ]
    out.loc[fill, "identity_evidence_reference_date"] = out.loc[
        fill, "fca_name_evidence_reference_date"
    ]
    out.loc[fill, "identity_policy"] = "historical_identity"
    out.loc[fill, "identity_resolution_method"] = "CVM_FCA_ISSUER_NAME_UNIQUE"
    out.loc[fill, "identity_evidence_source"] = "CVM_FCA_GERAL_NAME"

    evidence_date = pd.to_datetime(out.get("identity_evidence_available_from"), errors="coerce", utc=True)
    trade_date = pd.to_datetime(out["trade_date"], errors="coerce", utc=True)
    resolved_after_mask = out["identity_mapping_status"].eq("resolved")
    out["identity_reconstruction_uses_later_evidence"] = (
        resolved_after_mask & evidence_date.notna() & (evidence_date > trade_date)
    )

    total_volume = out["financial_volume"].sum()
    mapped_volume = out.loc[resolved_after_mask, "financial_volume"].sum()
    ambiguous_short_names = mapping.loc[
        mapping["fca_name_mapping_status"].eq("ambiguous_name_evidence"), "issuer_short_name"
    ].nunique()
    audit = FCANameEnrichmentAudit(
        rows=len(out),
        resolved_before=resolved_before,
        resolved_after=int(resolved_after_mask.sum()),
        newly_resolved_rows=int(fill.sum()),
        disagreement_rows=int(disagreement.sum()),
        ambiguous_short_names=int(ambiguous_short_names),
        mapped_row_ratio=float(resolved_after_mask.mean()) if len(out) else 0.0,
        mapped_volume_ratio=float(mapped_volume / total_volume) if total_volume > 0 else 0.0,
        unique_issuers=out.loc[resolved_after_mask, "issuer_id"].nunique(),
    )
    drop_columns = [
        "fca_name_issuer_id",
        "fca_name_mapping_status",
        "fca_name_matched_name",
        "fca_name_evidence_available_from",
        "fca_name_evidence_reference_date",
        "fca_name_candidate_issuers",
    ]
    return out.drop(columns=[column for column in drop_columns if column in out.columns]).reset_index(drop=True), audit

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .b3_isin import ExactIsinEnrichmentAudit, enrich_historical_identity_with_exact_isin

_REQUIRED = {
    "security_id",
    "issuer_id",
    "identity_evidence_available_from",
    "registry_mapping_status",
}


def combine_b3_isin_registries(registries: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Combine official B3 ISIN registry snapshots without losing old securities.

    Historical snapshots are valuable because the current EMISSOR file can omit
    cancelled issuers while NUMERACA still contains their securities. A security is
    promoted only when every supplied official snapshot that maps that ISIN agrees
    on the same issuer. Cross-vintage disagreement therefore fails closed.
    """

    frames = [frame.copy() for frame in registries if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=sorted(_REQUIRED))
    for frame in frames:
        missing = _REQUIRED - set(frame.columns)
        if missing:
            raise ValueError(f"missing B3 registry columns: {sorted(missing)}")
        frame["security_id"] = frame["security_id"].astype(str).str.strip().str.upper()
        frame["identity_evidence_available_from"] = pd.to_datetime(
            frame["identity_evidence_available_from"], errors="coerce", utc=True
        )
        if frame["identity_evidence_available_from"].isna().any():
            raise ValueError("registry history contains invalid evidence timestamps")

    combined = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates()
    issuer_counts = combined.groupby("security_id")["issuer_id"].nunique(dropna=True)
    ambiguous = set(issuer_counts[issuer_counts > 1].index.astype(str))
    combined["registry_mapping_status"] = combined["security_id"].map(
        lambda value: "ambiguous_registry" if value in ambiguous else "resolved"
    )
    # For a stable mapping retain the newest available official snapshot while old
    # snapshots still keep securities which disappeared from later registries.
    combined = combined.sort_values(
        ["security_id", "identity_evidence_available_from"], kind="stable"
    ).drop_duplicates(["security_id", "issuer_id"], keep="last")
    return combined.reset_index(drop=True)


def enrich_historical_identity_with_registry_history(
    universe: pd.DataFrame,
    registry_history: pd.DataFrame,
) -> tuple[pd.DataFrame, ExactIsinEnrichmentAudit]:
    """Apply exact ISIN identity from a multi-vintage B3 registry with provenance."""

    enriched, audit = enrich_historical_identity_with_exact_isin(universe, registry_history)
    resolved_registry = registry_history.loc[
        registry_history["registry_mapping_status"].eq("resolved")
    ].copy()
    if resolved_registry.empty:
        return enriched, audit
    counts = resolved_registry.groupby("security_id")["issuer_id"].nunique(dropna=True)
    ambiguous = set(counts[counts > 1].index.astype(str))
    resolved_registry = resolved_registry.loc[~resolved_registry["security_id"].isin(ambiguous)]
    resolved_registry = resolved_registry.sort_values(
        ["security_id", "identity_evidence_available_from"], kind="stable"
    ).drop_duplicates("security_id", keep="last")
    source_columns = ["security_id", "identity_evidence_available_from"]
    if "identity_evidence_source" in resolved_registry.columns:
        source_columns.append("identity_evidence_source")
    source = resolved_registry[source_columns].rename(
        columns={
            "identity_evidence_available_from": "__registry_available_from",
            "identity_evidence_source": "__registry_source",
        }
    )
    out = enriched.merge(source, on="security_id", how="left", validate="many_to_one")
    exact = out["identity_resolution_method"].eq("B3_ISIN_EXACT") & out["__registry_available_from"].notna()
    out.loc[exact, "identity_evidence_available_from"] = out.loc[exact, "__registry_available_from"]
    if "__registry_source" in out.columns:
        out.loc[exact, "identity_evidence_source"] = out.loc[exact, "__registry_source"]
    return out.drop(
        columns=[column for column in ("__registry_available_from", "__registry_source") if column in out]
    ).reset_index(drop=True), audit

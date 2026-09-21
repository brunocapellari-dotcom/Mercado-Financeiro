from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class LendingIdentityAudit:
    rows: int
    source_exact_isin_rows: int
    master_verified_rows: int
    master_resolved_rows: int
    unresolved_rows: int


def resolve_lending_identity_asof(
    lending: pd.DataFrame,
    security_master: pd.DataFrame,
    *,
    require_complete: bool = False,
) -> tuple[pd.DataFrame, LendingIdentityAudit]:
    """Resolve/verify B3 lending identities against active SCD2 security history.

    Source-provided ISIN remains authoritative evidence, but a conflicting active
    ticker mapping is a hard failure. Rows without ISIN may be resolved only when
    exactly one security-master interval is active for that ticker/reference date.
    """

    lending_required = {"reference_date", "ticker", "security_id", "isin"}
    master_required = {
        "ticker",
        "security_id",
        "isin",
        "valid_from",
        "valid_to_exclusive",
    }
    missing_lending = lending_required - set(lending.columns)
    missing_master = master_required - set(security_master.columns)
    if missing_lending:
        raise ValueError(f"lending identity input missing columns: {sorted(missing_lending)}")
    if missing_master:
        raise ValueError(f"security master missing columns: {sorted(missing_master)}")

    out = lending.copy()
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce", utc=True)
    if out["reference_date"].isna().any():
        raise ValueError("lending reference_date contains null/invalid values")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    if out["ticker"].eq("").any():
        raise ValueError("lending ticker must not be blank")

    master = security_master.copy()
    master["valid_from"] = pd.to_datetime(master["valid_from"], errors="coerce", utc=True)
    master["valid_to_exclusive"] = pd.to_datetime(
        master["valid_to_exclusive"], errors="coerce", utc=True
    )
    if master["valid_from"].isna().any():
        raise ValueError("security master valid_from contains null/invalid values")
    master["ticker"] = master["ticker"].astype(str).str.strip().str.upper()
    if master["ticker"].eq("").any():
        raise ValueError("security master ticker must not be blank")

    source_exact = 0
    verified = 0
    resolved = 0
    unresolved = 0
    statuses: list[str] = []
    resolved_security_ids: list[object] = []
    resolved_isins: list[object] = []

    for row in out.itertuples(index=False):
        reference = pd.Timestamp(row.reference_date)
        ticker = str(row.ticker)
        candidates = master.loc[
            master["ticker"].eq(ticker)
            & master["valid_from"].le(reference)
            & (
                master["valid_to_exclusive"].isna()
                | master["valid_to_exclusive"].gt(reference)
            )
        ].copy()

        source_security = None if pd.isna(row.security_id) else str(row.security_id)
        source_isin = None if pd.isna(row.isin) else str(row.isin)

        if source_security is not None:
            source_exact += 1
            if candidates.empty:
                statuses.append("exact_isin_source")
                resolved_security_ids.append(source_security)
                resolved_isins.append(source_isin)
                continue

            matching = candidates.loc[candidates["security_id"].astype(str).eq(source_security)]
            if len(matching) == 1:
                verified += 1
                master_isin = matching.iloc[0]["isin"]
                if pd.notna(master_isin) and source_isin is not None and str(master_isin) != source_isin:
                    raise ValueError(
                        f"B3 lending ISIN conflict for {ticker} at {reference.isoformat()}"
                    )
                statuses.append("exact_isin_master_verified")
                resolved_security_ids.append(source_security)
                resolved_isins.append(source_isin or (str(master_isin) if pd.notna(master_isin) else None))
                continue
            if len(matching) > 1:
                raise ValueError(
                    f"ambiguous security-master rows for exact lending identity "
                    f"{ticker}/{source_security} at {reference.isoformat()}"
                )
            active_ids = sorted(set(candidates["security_id"].astype(str)))
            raise ValueError(
                f"B3 lending/source security conflicts with active security master for "
                f"{ticker} at {reference.isoformat()}: source={source_security} active={active_ids}"
            )

        if candidates.empty:
            unresolved += 1
            statuses.append("unresolved_ticker")
            resolved_security_ids.append(None)
            resolved_isins.append(None)
            continue

        candidate_ids = candidates["security_id"].astype(str).drop_duplicates()
        if len(candidate_ids) != 1:
            raise ValueError(
                f"ambiguous active ticker-to-security mapping for {ticker} "
                f"at {reference.isoformat()}: {sorted(candidate_ids.tolist())}"
            )
        chosen_id = candidate_ids.iloc[0]
        chosen_rows = candidates.loc[candidates["security_id"].astype(str).eq(chosen_id)]
        isins = chosen_rows["isin"].dropna().astype(str).drop_duplicates()
        if len(isins) > 1:
            raise ValueError(
                f"security master has multiple ISINs for {ticker}/{chosen_id} "
                f"at {reference.isoformat()}"
            )
        chosen_isin = isins.iloc[0] if len(isins) == 1 else None
        resolved += 1
        statuses.append("security_master_asof")
        resolved_security_ids.append(chosen_id)
        resolved_isins.append(chosen_isin)

    out["security_id"] = resolved_security_ids
    out["isin"] = resolved_isins
    out["identity_status"] = statuses

    if require_complete and out["security_id"].isna().any():
        sample = out.loc[out["security_id"].isna(), ["reference_date", "ticker"]].head(10)
        raise ValueError(
            "unresolved B3 lending identities remain: "
            + str(sample.to_dict(orient="records"))
        )

    audit = LendingIdentityAudit(
        rows=len(out),
        source_exact_isin_rows=source_exact,
        master_verified_rows=verified,
        master_resolved_rows=resolved,
        unresolved_rows=unresolved,
    )
    return out.reset_index(drop=True), audit

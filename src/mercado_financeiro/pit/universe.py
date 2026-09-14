from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

IdentityPolicy = Literal["strict_publication", "historical_identity"]


@dataclass(frozen=True)
class TradableUniverseAudit:
    rows: int
    mapped_rows: int
    unresolved_rows: int
    ambiguous_rows: int
    later_identity_evidence_rows: int
    mapped_row_ratio: float
    mapped_volume_ratio: float
    unique_securities: int
    unique_issuers: int


def resolve_fca_identity_asof(
    fca_history: pd.DataFrame,
    asof: str | pd.Timestamp,
    *,
    policy: IdentityPolicy = "strict_publication",
) -> pd.DataFrame:
    """Resolve ticker -> issuer at one date under an explicit time policy.

    ``strict_publication`` only admits FCA evidence received by CVM by the as-of
    date. ``historical_identity`` may use later FCA evidence solely to reconstruct
    static identifier history (ticker/CNPJ and reported trading interval). The latter
    must never be used to advance economic/fundamental values; its evidence receipt
    time is preserved so downstream audits can quantify ex-post identity usage.
    """
    if policy not in {"strict_publication", "historical_identity"}:
        raise ValueError(f"unsupported identity policy: {policy}")

    required = {
        "ticker",
        "issuer_id",
        "valid_from",
        "valid_to_exclusive",
        "reference_date",
        "available_from",
    }
    missing = required - set(fca_history.columns)
    if missing:
        raise ValueError(f"missing FCA identity columns: {sorted(missing)}")

    ts = pd.Timestamp(asof)
    frame = fca_history.copy()
    for column in ("valid_from", "valid_to_exclusive", "reference_date", "available_from"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    if frame[["valid_from", "reference_date", "available_from"]].isna().any().any():
        raise ValueError("FCA identity history contains invalid required dates")

    eligible = frame.loc[
        (frame["valid_from"] <= ts)
        & (frame["valid_to_exclusive"].isna() | (ts < frame["valid_to_exclusive"]))
    ].copy()
    if policy == "strict_publication":
        eligible = eligible.loc[eligible["available_from"] <= ts].copy()

    if eligible.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "issuer_id",
                "identity_mapping_status",
                "identity_evidence_available_from",
                "identity_evidence_reference_date",
                "identity_policy",
            ]
        )

    issuer_counts = eligible.groupby("ticker", dropna=False)["issuer_id"].nunique()
    ambiguous = set(issuer_counts[issuer_counts > 1].index.astype(str))

    eligible = eligible.sort_values(
        ["ticker", "reference_date", "available_from"], kind="stable"
    )
    latest = eligible.drop_duplicates("ticker", keep="last").copy()
    latest["identity_mapping_status"] = "resolved"
    latest.loc[latest["ticker"].isin(ambiguous), "identity_mapping_status"] = "ambiguous_issuer"
    latest.loc[latest["identity_mapping_status"] != "resolved", "issuer_id"] = pd.NA
    latest = latest.rename(
        columns={
            "available_from": "identity_evidence_available_from",
            "reference_date": "identity_evidence_reference_date",
        }
    )
    latest["identity_policy"] = policy
    return latest[
        [
            "ticker",
            "issuer_id",
            "identity_mapping_status",
            "identity_evidence_available_from",
            "identity_evidence_reference_date",
            "identity_policy",
        ]
    ].reset_index(drop=True)


def build_tradable_universe_pit(
    quotes: pd.DataFrame,
    fca_history: pd.DataFrame,
    *,
    identity_policy: IdentityPolicy = "historical_identity",
) -> tuple[pd.DataFrame, TradableUniverseAudit]:
    """Create the observed daily equity universe from actual COTAHIST trading rows.

    Universe membership comes only from an observed regular-share quote on that date,
    so delisted firms remain in historical samples and future constituents cannot be
    injected. FCA is used only to name the issuer behind the already-observed ticker.
    """
    required_quotes = {
        "trade_date",
        "security_id",
        "isin",
        "ticker",
        "close_price",
        "financial_volume",
        "trades",
        "quantity",
        "bdi_code",
        "specification",
    }
    missing = required_quotes - set(quotes.columns)
    if missing:
        raise ValueError(f"missing quote columns: {sorted(missing)}")

    frame = quotes.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["financial_volume"] = pd.to_numeric(frame["financial_volume"], errors="coerce")
    if frame[["trade_date", "financial_volume"]].isna().any().any():
        raise ValueError("quotes contain invalid trade_date/financial_volume")
    if frame.duplicated(["trade_date", "security_id"], keep=False).any():
        raise ValueError("quotes contain duplicate security/date observations")

    mapped_parts: list[pd.DataFrame] = []
    for trade_date, day_quotes in frame.groupby("trade_date", sort=True):
        mapping = resolve_fca_identity_asof(
            fca_history,
            trade_date,
            policy=identity_policy,
        )
        day = day_quotes.merge(mapping, on="ticker", how="left", validate="many_to_one")
        day["identity_mapping_status"] = day["identity_mapping_status"].fillna(
            "unresolved_no_fca_evidence"
        )
        day["identity_policy"] = day["identity_policy"].fillna(identity_policy)
        mapped_parts.append(day)

    out = pd.concat(mapped_parts, ignore_index=True) if mapped_parts else frame.copy()
    if out.empty:
        audit = TradableUniverseAudit(0, 0, 0, 0, 0, 0.0, 0.0, 0, 0)
        return out, audit

    evidence_date = pd.to_datetime(out["identity_evidence_available_from"], errors="coerce")
    out["identity_reconstruction_uses_later_evidence"] = (
        out["identity_mapping_status"].eq("resolved") & (evidence_date > out["trade_date"])
    )
    out["tradable_observed"] = True
    out["universe_source"] = "B3_COTAHIST_OBSERVED_TRADE"

    resolved = out["identity_mapping_status"].eq("resolved")
    ambiguous = out["identity_mapping_status"].eq("ambiguous_issuer")
    mapped_volume = out.loc[resolved, "financial_volume"].sum()
    total_volume = out["financial_volume"].sum()
    mapped_volume_ratio = float(mapped_volume / total_volume) if total_volume > 0 else 0.0

    audit = TradableUniverseAudit(
        rows=len(out),
        mapped_rows=int(resolved.sum()),
        unresolved_rows=int((~resolved & ~ambiguous).sum()),
        ambiguous_rows=int(ambiguous.sum()),
        later_identity_evidence_rows=int(out["identity_reconstruction_uses_later_evidence"].sum()),
        mapped_row_ratio=float(resolved.mean()),
        mapped_volume_ratio=mapped_volume_ratio,
        unique_securities=out["security_id"].nunique(),
        unique_issuers=out.loc[resolved, "issuer_id"].nunique(),
    )
    return out.reset_index(drop=True), audit

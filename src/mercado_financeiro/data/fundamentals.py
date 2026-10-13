from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FundamentalsAudit:
    rows: int
    issuers: int
    metrics: int
    duplicate_vintages: int
    invalid_availability_rows: int


def validate_fundamental_observations(frame: pd.DataFrame) -> tuple[pd.DataFrame, FundamentalsAudit]:
    """Validate canonical long-form PIT fundamentals.

    Every value keeps accounting reference date and the timestamp at which that
    exact filing vintage became available. Revised filings therefore append new
    versions instead of overwriting older evidence.
    """

    required = {
        "issuer_id",
        "metric",
        "value",
        "reference_date",
        "available_from",
        "filing_version",
        "source",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing fundamental fields: {sorted(missing)}")
    out = frame.copy()
    out["issuer_id"] = out["issuer_id"].astype(str).str.strip()
    out["metric"] = out["metric"].astype(str).str.strip()
    out["source"] = out["source"].astype(str).str.strip()
    if out[["issuer_id", "metric", "source"]].eq("").any().any():
        raise ValueError("issuer_id/metric/source cannot be empty")
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce", utc=True)
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce", utc=True)
    out["filing_version"] = pd.to_numeric(out["filing_version"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if out[["reference_date", "available_from", "filing_version", "value"]].isna().any().any():
        raise ValueError("invalid fundamental value/date/version")
    if (out["filing_version"] < 0).any():
        raise ValueError("filing_version cannot be negative")

    invalid_availability = out["available_from"] < out["reference_date"]
    if invalid_availability.any():
        raise ValueError("fundamental available_from cannot precede reference_date")
    key = ["issuer_id", "metric", "reference_date", "filing_version", "source"]
    duplicate_vintages = int(out.duplicated(key).sum())
    if duplicate_vintages:
        raise ValueError("duplicate fundamental filing vintages")

    audit = FundamentalsAudit(
        rows=len(out),
        issuers=out["issuer_id"].nunique(),
        metrics=out["metric"].nunique(),
        duplicate_vintages=duplicate_vintages,
        invalid_availability_rows=int(invalid_availability.sum()),
    )
    return out.sort_values(
        ["issuer_id", "metric", "available_from", "reference_date", "filing_version"],
        kind="stable",
    ).reset_index(drop=True), audit


def fundamentals_asof(
    frame: pd.DataFrame,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    validated, _ = validate_fundamental_observations(frame)
    ts = pd.to_datetime(cutoff, errors="raise", utc=True)
    eligible = validated.loc[validated["available_from"] <= ts].copy()
    if eligible.empty:
        return eligible
    eligible = eligible.sort_values(
        ["issuer_id", "metric", "available_from", "reference_date", "filing_version"],
        kind="stable",
    )
    return (
        eligible.groupby(["issuer_id", "metric"], as_index=False, sort=False)
        .tail(1)
        .reset_index(drop=True)
    )

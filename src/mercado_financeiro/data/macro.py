from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MacroAudit:
    rows: int
    series: int
    duplicate_vintages: int
    future_availability_rows: int


def validate_macro_observations(frame: pd.DataFrame) -> tuple[pd.DataFrame, MacroAudit]:
    """Validate canonical long-form macro observations with explicit vintages."""

    required = {
        "series_id",
        "reference_date",
        "available_from",
        "value",
        "source",
        "vintage_id",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing macro fields: {sorted(missing)}")
    out = frame.copy()
    out["series_id"] = out["series_id"].astype(str).str.strip()
    out["source"] = out["source"].astype(str).str.strip()
    out["vintage_id"] = out["vintage_id"].astype(str).str.strip()
    if out[["series_id", "source", "vintage_id"]].eq("").any().any():
        raise ValueError("series_id/source/vintage_id cannot be empty")
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce", utc=True)
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce", utc=True)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if out[["reference_date", "available_from", "value"]].isna().any().any():
        raise ValueError("invalid macro value/date")
    future = out["available_from"] < out["reference_date"]
    if future.any():
        raise ValueError("macro available_from cannot precede reference_date")
    key = ["series_id", "reference_date", "vintage_id", "source"]
    duplicate_vintages = int(out.duplicated(key).sum())
    if duplicate_vintages:
        raise ValueError("duplicate macro vintages")
    return (
        out.sort_values(
            ["series_id", "available_from", "reference_date", "vintage_id"], kind="stable"
        ).reset_index(drop=True),
        MacroAudit(
            rows=len(out),
            series=out["series_id"].nunique(),
            duplicate_vintages=duplicate_vintages,
            future_availability_rows=int(future.sum()),
        ),
    )


def macro_asof(frame: pd.DataFrame, cutoff: str | pd.Timestamp) -> pd.DataFrame:
    validated, _ = validate_macro_observations(frame)
    ts = pd.to_datetime(cutoff, errors="raise", utc=True)
    eligible = validated.loc[validated["available_from"] <= ts].copy()
    if eligible.empty:
        return eligible
    eligible = eligible.sort_values(
        ["series_id", "reference_date", "available_from", "vintage_id"], kind="stable"
    )
    # Keep the newest known vintage for each historical reference observation.
    return (
        eligible.groupby(["series_id", "reference_date"], as_index=False, sort=False)
        .tail(1)
        .reset_index(drop=True)
    )

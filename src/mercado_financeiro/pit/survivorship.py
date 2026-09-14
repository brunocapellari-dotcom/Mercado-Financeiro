from __future__ import annotations

import pandas as pd


def coverage_audit(df: pd.DataFrame) -> pd.DataFrame:
    required = {"year", "observations", "mapped_obs_share", "mapped_volume_share"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    out = df.copy()
    out["unmapped_observations_est"] = (
        out["observations"] * (1.0 - out["mapped_obs_share"])
    ).round().astype("int64")
    out["obs_gate_99pct"] = out["mapped_obs_share"] >= 0.99
    out["volume_gate_99pct"] = out["mapped_volume_share"] >= 0.99
    return out

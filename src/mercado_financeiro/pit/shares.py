from __future__ import annotations

import pandas as pd


_REQUIRED_DFP_COLUMNS = {
    "CNPJ_CIA",
    "DT_REFER",
    "VERSAO",
    "available_from",
    "QT_ACAO_ORDIN_CAP_INTEGR",
    "QT_ACAO_PREF_CAP_INTEGR",
    "QT_ACAO_TOTAL_CAP_INTEGR",
    "QT_ACAO_ORDIN_TESOURO",
    "QT_ACAO_PREF_TESOURO",
    "QT_ACAO_TOTAL_TESOURO",
}


def normalize_dfp_shares_outstanding(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize audited DFP capital composition into PIT share counts.

    This function expects `available_from` to have already been derived from the
    exact filing version represented by the source row. It fails closed on
    arithmetic inconsistencies instead of repairing them silently.
    """
    missing = _REQUIRED_DFP_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    out = df.copy()
    out["reference_date"] = pd.to_datetime(out["DT_REFER"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    if out[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("reference_date/available_from contains null or invalid values")

    out["filing_version"] = pd.to_numeric(out["VERSAO"], errors="coerce")
    if out["filing_version"].isna().any():
        raise ValueError("VERSAO contains null/non-numeric values")
    out["filing_version"] = out["filing_version"].astype("int64")

    numeric_map = {
        "ordinary_issued": "QT_ACAO_ORDIN_CAP_INTEGR",
        "preferred_issued": "QT_ACAO_PREF_CAP_INTEGR",
        "total_issued": "QT_ACAO_TOTAL_CAP_INTEGR",
        "ordinary_treasury": "QT_ACAO_ORDIN_TESOURO",
        "preferred_treasury": "QT_ACAO_PREF_TESOURO",
        "total_treasury": "QT_ACAO_TOTAL_TESOURO",
    }
    for target, source in numeric_map.items():
        out[target] = pd.to_numeric(out[source], errors="coerce")
        if out[target].isna().any():
            raise ValueError(f"{source} contains null/non-numeric values")
        if (out[target] < 0).any():
            raise ValueError(f"{source} contains negative values")

    issued_mismatch = out["total_issued"] != out["ordinary_issued"] + out["preferred_issued"]
    if issued_mismatch.any():
        raise ValueError(f"issued share totals mismatch on {int(issued_mismatch.sum())} rows")

    treasury_mismatch = out["total_treasury"] != (
        out["ordinary_treasury"] + out["preferred_treasury"]
    )
    if treasury_mismatch.any():
        raise ValueError(f"treasury share totals mismatch on {int(treasury_mismatch.sum())} rows")

    if (out["ordinary_treasury"] > out["ordinary_issued"]).any():
        raise ValueError("ordinary treasury shares exceed issued shares")
    if (out["preferred_treasury"] > out["preferred_issued"]).any():
        raise ValueError("preferred treasury shares exceed issued shares")

    out["ordinary_outstanding"] = out["ordinary_issued"] - out["ordinary_treasury"]
    out["preferred_outstanding"] = out["preferred_issued"] - out["preferred_treasury"]
    out["total_outstanding"] = out["ordinary_outstanding"] + out["preferred_outstanding"]
    out["issuer_id"] = out["CNPJ_CIA"]
    out["source"] = "CVM_DFP_COMPOSICAO_CAPITAL"
    out["vintage_mode"] = "conservative_latest_snapshot"

    columns = [
        "issuer_id",
        "reference_date",
        "available_from",
        "filing_version",
        "ordinary_issued",
        "preferred_issued",
        "total_issued",
        "ordinary_treasury",
        "preferred_treasury",
        "total_treasury",
        "ordinary_outstanding",
        "preferred_outstanding",
        "total_outstanding",
        "source",
        "vintage_mode",
    ]
    return out[columns].copy()


def shares_outstanding_asof(df: pd.DataFrame, asof: str | pd.Timestamp) -> pd.DataFrame:
    """Select the latest economically eligible share count per issuer at `asof`."""
    required = {"issuer_id", "reference_date", "available_from", "filing_version"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    ts = pd.Timestamp(asof)
    out = df.copy()
    out["reference_date"] = pd.to_datetime(out["reference_date"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce")
    if out[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("reference_date/available_from contains null or invalid values")

    eligible = out.loc[(out["available_from"] <= ts) & (out["reference_date"] <= ts)].copy()
    if eligible.empty:
        return eligible

    eligible = eligible.sort_values(
        ["issuer_id", "reference_date", "available_from", "filing_version"],
        kind="stable",
    )
    return eligible.groupby("issuer_id", as_index=False, sort=False).tail(1).reset_index(drop=True)

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import zipfile

import pandas as pd


@dataclass(frozen=True)
class SnapshotAudit:
    dataset: str
    year: int
    rows: int
    companies: int
    missing_available_from: int
    max_versions_per_company: int
    receipt_min: pd.Timestamp | None
    receipt_median: pd.Timestamp | None
    receipt_max: pd.Timestamp | None


def _inner_zip_bytes(path: str | Path) -> bytes:
    """Return bytes of a CVM ZIP, accepting our artifact wrapper or a raw ZIP."""
    path = Path(path)
    data = path.read_bytes()
    with zipfile.ZipFile(BytesIO(data)) as outer:
        names = outer.namelist()
        if len(names) == 1 and names[0].lower().endswith(".zip"):
            return outer.read(names[0])
    return data


def _read_csv(inner_zip: bytes, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(BytesIO(inner_zip)) as zf:
        with zf.open(member) as f:
            return pd.read_csv(f, sep=";", encoding="latin-1", dtype=str)


def audit_fre_capital_social(path: str | Path, year: int) -> tuple[pd.DataFrame, SnapshotAudit]:
    """Attach the true availability date to FRE capital-social rows.

    Structured FRE sections are latest-snapshot materializations. `available_from`
    must therefore come from the submission ledger's DT_RECEB for the exact
    ID_Documento/Versao represented by each row.
    """
    inner = _inner_zip_bytes(path)
    meta = _read_csv(inner, f"fre_cia_aberta_{year}.csv")
    cap = _read_csv(inner, f"fre_cia_aberta_capital_social_{year}.csv")

    meta["DT_RECEB"] = pd.to_datetime(meta["DT_RECEB"], errors="coerce")
    keys = cap[["CNPJ_Companhia", "Data_Referencia", "Versao", "ID_Documento"]].drop_duplicates()
    ledger = meta[["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC", "DT_RECEB"]].copy()
    out = cap.merge(
        ledger,
        left_on=["CNPJ_Companhia", "Data_Referencia", "Versao", "ID_Documento"],
        right_on=["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"],
        how="left",
        validate="many_to_one",
    ).rename(columns={"DT_RECEB": "available_from"})

    per_company_versions = keys.groupby("CNPJ_Companhia")["Versao"].nunique()
    receipt = out[["CNPJ_Companhia", "available_from"]].drop_duplicates()["available_from"]
    audit = SnapshotAudit(
        dataset="FRE_CAPITAL_SOCIAL",
        year=year,
        rows=len(out),
        companies=out["CNPJ_Companhia"].nunique(),
        missing_available_from=int(out["available_from"].isna().sum()),
        max_versions_per_company=int(per_company_versions.max()),
        receipt_min=receipt.min(),
        receipt_median=receipt.median(),
        receipt_max=receipt.max(),
    )
    if audit.missing_available_from:
        raise ValueError(f"FRE {year}: {audit.missing_available_from} rows lack available_from")
    return out, audit


def audit_dfp_composition_capital(path: str | Path, year: int) -> tuple[pd.DataFrame, SnapshotAudit]:
    """Attach a conservative availability date to DFP capital-composition rows."""
    inner = _inner_zip_bytes(path)
    meta = _read_csv(inner, f"dfp_cia_aberta_{year}.csv")
    comp = _read_csv(inner, f"dfp_cia_aberta_composicao_capital_{year}.csv")

    meta["DT_RECEB"] = pd.to_datetime(meta["DT_RECEB"], errors="coerce")
    # Section rows do not expose ID_DOC. If metadata duplicates company/reference/version,
    # use the latest receipt so the conservative track never makes data available early.
    ledger = meta.groupby(["CNPJ_CIA", "DT_REFER", "VERSAO"], as_index=False)["DT_RECEB"].max()
    out = comp.merge(
        ledger,
        on=["CNPJ_CIA", "DT_REFER", "VERSAO"],
        how="left",
        validate="many_to_one",
    ).rename(columns={"DT_RECEB": "available_from"})

    per_company_versions = comp.groupby("CNPJ_CIA")["VERSAO"].nunique()
    receipt = out[["CNPJ_CIA", "available_from"]].drop_duplicates()["available_from"]
    audit = SnapshotAudit(
        dataset="DFP_COMPOSICAO_CAPITAL",
        year=year,
        rows=len(out),
        companies=out["CNPJ_CIA"].nunique(),
        missing_available_from=int(out["available_from"].isna().sum()),
        max_versions_per_company=int(per_company_versions.max()),
        receipt_min=receipt.min(),
        receipt_median=receipt.median(),
        receipt_max=receipt.max(),
    )
    if audit.missing_available_from:
        raise ValueError(f"DFP {year}: {audit.missing_available_from} rows lack available_from")
    return out, audit


def available_asof(df: pd.DataFrame, asof: str | pd.Timestamp) -> pd.DataFrame:
    """Return only rows whose represented version was actually available by `asof`."""
    if "available_from" not in df.columns:
        raise ValueError("dataset must include available_from")
    ts = pd.Timestamp(asof)
    available = pd.to_datetime(df["available_from"], errors="coerce")
    if available.isna().any():
        raise ValueError("available_from contains null/unparseable values")
    return df.loc[available <= ts].copy()

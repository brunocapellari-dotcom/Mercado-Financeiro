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


def _fre_section_with_availability(
    inner_zip: bytes,
    year: int,
    *,
    member: str,
    dataset: str,
) -> tuple[pd.DataFrame, SnapshotAudit]:
    """Join one FRE child section to the exact filing receipt ledger.

    FRE child sections expose ``ID_Documento`` and therefore must be linked to
    ``DT_RECEB`` by document id plus issuer/reference/version. A child row that cannot
    be tied to its exact filing fails closed rather than receiving a synthetic date.
    """
    meta = _read_csv(inner_zip, f"fre_cia_aberta_{year}.csv")
    section = _read_csv(inner_zip, member)

    required_meta = {"CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC", "DT_RECEB"}
    required_section = {
        "CNPJ_Companhia",
        "Data_Referencia",
        "Versao",
        "ID_Documento",
    }
    missing_meta = required_meta - set(meta.columns)
    missing_section = required_section - set(section.columns)
    if missing_meta:
        raise ValueError(f"FRE {year} ledger missing columns: {sorted(missing_meta)}")
    if missing_section:
        raise ValueError(f"FRE {year} {member} missing columns: {sorted(missing_section)}")

    meta = meta.copy()
    meta["DT_RECEB"] = pd.to_datetime(meta["DT_RECEB"], errors="coerce")
    if meta["DT_RECEB"].isna().any():
        raise ValueError(f"FRE {year} filing ledger contains invalid DT_RECEB")

    ledger = meta[["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC", "DT_RECEB"]].copy()
    ledger_conflicts = (
        ledger.groupby(["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"], dropna=False)[
            "DT_RECEB"
        ]
        .nunique(dropna=False)
        .gt(1)
    )
    if ledger_conflicts.any():
        raise ValueError(f"FRE {year} filing ledger contains conflicting receipt timestamps")
    ledger = ledger.drop_duplicates(
        ["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"], keep="last"
    )

    out = section.merge(
        ledger,
        left_on=["CNPJ_Companhia", "Data_Referencia", "Versao", "ID_Documento"],
        right_on=["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"],
        how="left",
        validate="many_to_one",
    ).rename(columns={"DT_RECEB": "available_from"})

    versions = (
        section[["CNPJ_Companhia", "Versao"]]
        .drop_duplicates()
        .groupby("CNPJ_Companhia")["Versao"]
        .nunique()
    )
    receipt = out[["CNPJ_Companhia", "available_from"]].drop_duplicates()[
        "available_from"
    ]
    audit = SnapshotAudit(
        dataset=dataset,
        year=year,
        rows=len(out),
        companies=out["CNPJ_Companhia"].nunique(),
        missing_available_from=int(out["available_from"].isna().sum()),
        max_versions_per_company=int(versions.max()) if len(versions) else 0,
        receipt_min=receipt.min() if len(receipt) else None,
        receipt_median=receipt.median() if len(receipt) else None,
        receipt_max=receipt.max() if len(receipt) else None,
    )
    if audit.missing_available_from:
        raise ValueError(
            f"FRE {year} {dataset}: {audit.missing_available_from} rows lack available_from"
        )
    return out, audit


def audit_fre_capital_social(path: str | Path, year: int) -> tuple[pd.DataFrame, SnapshotAudit]:
    """Attach the true filing-availability date to FRE capital-social rows."""
    inner = _inner_zip_bytes(path)
    return _fre_section_with_availability(
        inner,
        year,
        member=f"fre_cia_aberta_capital_social_{year}.csv",
        dataset="FRE_CAPITAL_SOCIAL",
    )


def audit_fre_treasury_last_exercise(
    path: str | Path,
    year: int,
) -> tuple[pd.DataFrame, SnapshotAudit]:
    """Attach exact filing receipts to FRE end-of-exercise treasury-share rows."""
    inner = _inner_zip_bytes(path)
    return _fre_section_with_availability(
        inner,
        year,
        member=f"fre_cia_aberta_valor_mobiliario_tesouraria_ultimo_exercicio_{year}.csv",
        dataset="FRE_TREASURY_LAST_EXERCISE",
    )


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

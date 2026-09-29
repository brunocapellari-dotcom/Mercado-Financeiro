from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from mercado_financeiro.data.fundamentals import validate_fundamental_observations


@dataclass(frozen=True)
class CVMStatementSchema:
    issuer: str
    account_code: str
    account_name: str
    value: str
    reference_date: str
    available_from: str
    filing_version: str
    statement: str | None = None


# Deliberately small and exact. Derived metrics such as EBITDA are not invented
# from account labels; they belong in a separately versioned transformation.
CANONICAL_CVM_ACCOUNT_MAP: Mapping[tuple[str, str], str] = {
    ("DRE", "3.01"): "net_revenue",
    ("DRE", "3.05"): "ebit",
    ("DRE", "3.11"): "net_income_consolidated",
    ("BPA", "1"): "total_assets",
    ("BPA", "1.01.01"): "cash_and_cash_equivalents",
    ("BPP", "2.03"): "equity",
}


def _cvm_number(value: object) -> float:
    direct = pd.to_numeric(value, errors="coerce")
    if not pd.isna(direct):
        return float(direct)
    text = str(value).strip()
    if "," in text:
        candidate = text.replace(".", "").replace(",", ".")
        parsed = pd.to_numeric(candidate, errors="coerce")
        if not pd.isna(parsed):
            return float(parsed)
    raise ValueError(f"invalid CVM accounting value: {value!r}")


def normalize_cvm_statement_rows(
    frame: pd.DataFrame,
    *,
    schema: CVMStatementSchema,
    statement_name: str | None = None,
    source: str = "CVM",
) -> pd.DataFrame:
    """Normalize CVM DFP/ITR statement rows without losing original accounts.

    The output is long-form and point-in-time. Exact CVM account codes receive a
    canonical metric when the mapping is unambiguous; all other rows retain their
    original code/name and a null canonical metric instead of a guessed mapping.
    """

    columns = {
        schema.issuer,
        schema.account_code,
        schema.account_name,
        schema.value,
        schema.reference_date,
        schema.available_from,
        schema.filing_version,
    }
    if schema.statement is not None:
        columns.add(schema.statement)
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"missing CVM statement columns: {sorted(missing)}")
    if statement_name is None and schema.statement is None:
        raise ValueError("statement_name or schema.statement is required")

    out = pd.DataFrame(
        {
            "issuer_id": frame[schema.issuer].astype(str).str.strip(),
            "account_code": frame[schema.account_code].astype(str).str.strip(),
            "account_name": frame[schema.account_name].astype(str).str.strip(),
            "value": frame[schema.value].map(_cvm_number),
            "reference_date": pd.to_datetime(
                frame[schema.reference_date], errors="coerce", utc=True
            ),
            "available_from": pd.to_datetime(
                frame[schema.available_from], errors="coerce", utc=True
            ),
            "filing_version": pd.to_numeric(frame[schema.filing_version], errors="coerce"),
        }
    )
    if schema.statement is None:
        out["statement"] = str(statement_name).strip().upper()
    else:
        out["statement"] = frame[schema.statement].astype(str).str.strip().str.upper()
    if out[["issuer_id", "account_code", "account_name", "statement"]].eq("").any().any():
        raise ValueError("CVM identity/account/statement fields cannot be empty")
    if out[["reference_date", "available_from", "filing_version"]].isna().any().any():
        raise ValueError("invalid CVM statement date/version")
    if (out["available_from"] < out["reference_date"]).any():
        raise ValueError("CVM statement cannot be available before its reference date")

    out["metric"] = [
        CANONICAL_CVM_ACCOUNT_MAP.get((statement, account), pd.NA)
        for statement, account in zip(out["statement"], out["account_code"], strict=True)
    ]
    out["source"] = source
    out["accounting_basis"] = "CPC_IFRS_CVM"

    mapped = out.loc[out["metric"].notna()].copy()
    if not mapped.empty:
        validate_fundamental_observations(
            mapped[
                [
                    "issuer_id",
                    "metric",
                    "value",
                    "reference_date",
                    "available_from",
                    "filing_version",
                    "source",
                ]
            ]
        )
    key = [
        "issuer_id",
        "statement",
        "account_code",
        "reference_date",
        "filing_version",
        "source",
    ]
    if out.duplicated(key).any():
        raise ValueError("duplicate CVM statement filing rows")
    return out.sort_values(key, kind="stable").reset_index(drop=True)


__all__ = [
    "CANONICAL_CVM_ACCOUNT_MAP",
    "CVMStatementSchema",
    "normalize_cvm_statement_rows",
]

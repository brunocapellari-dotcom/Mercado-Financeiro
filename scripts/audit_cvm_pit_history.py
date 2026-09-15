from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import zipfile

import pandas as pd

from mercado_financeiro.pit import (
    audit_dfp_composition_capital,
    audit_fre_capital_social,
    normalize_dfp_shares_outstanding,
)
from mercado_financeiro.security import DownloadPolicy, RetryPolicy, download_https_with_retry

DFP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
FRE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip"

# CVM added the structured DFP/ITR "Dados da Empresa / Composição do Capital"
# section to the open-data packages in November 2024. Older annual archives that
# were last materialized before that change can legitimately lack the CSV even
# though the original filing itself contained the information. We therefore test
# the full DFP ledger at early/middle/recent boundaries and require the structured
# share section only on vintages whose current archive is expected to expose it.
DFP_LEDGER_BOUNDARY_YEARS = (2011, 2018, 2025)
DFP_SHARE_BOUNDARY_YEARS = (2020, 2025)
FRE_BOUNDARY_YEARS = (2011, 2018, 2025)
POLICY = DownloadPolicy(max_bytes=1_000_000_000, timeout_seconds=240.0)
RETRY = RetryPolicy(attempts=5, initial_delay_seconds=2.0, max_delay_seconds=20.0)


def _download(url: str, target: Path) -> tuple[int, str]:
    payload = download_https_with_retry(url, POLICY, retry_policy=RETRY)
    target.write_bytes(payload)
    return len(payload), sha256(payload).hexdigest()


def _read_zip_csv(path: Path, member: str) -> pd.DataFrame:
    payload = path.read_bytes()
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        with zf.open(member) as handle:
            return pd.read_csv(handle, sep=";", encoding="latin-1", dtype=str)


def _zip_members(path: Path) -> set[str]:
    with zipfile.ZipFile(BytesIO(path.read_bytes())) as zf:
        return set(zf.namelist())


def _audit_dfp_ledger(path: Path, year: int) -> dict[str, object]:
    member = f"dfp_cia_aberta_{year}.csv"
    members = _zip_members(path)
    if member not in members:
        raise RuntimeError(f"DFP {year}: missing canonical filing ledger {member}")
    ledger = _read_zip_csv(path, member)
    required = {"CNPJ_CIA", "DT_REFER", "VERSAO", "DT_RECEB"}
    missing = required - set(ledger.columns)
    if missing:
        raise RuntimeError(f"DFP {year}: ledger missing fields {sorted(missing)}")
    receipt = pd.to_datetime(ledger["DT_RECEB"], errors="coerce")
    missing_receipts = int(receipt.isna().sum())
    if missing_receipts:
        raise RuntimeError(f"DFP {year}: {missing_receipts} ledger rows lack DT_RECEB")
    composition_member = f"dfp_cia_aberta_composicao_capital_{year}.csv"
    return {
        "ledger_rows": len(ledger),
        "ledger_companies": int(ledger["CNPJ_CIA"].nunique()),
        "ledger_missing_receipts": missing_receipts,
        "receipt_min": str(receipt.min()),
        "receipt_max": str(receipt.max()),
        "composition_member_present": composition_member in members,
    }


def main() -> None:
    records: list[dict[str, object]] = []
    dfp_years = tuple(sorted(set(DFP_LEDGER_BOUNDARY_YEARS) | set(DFP_SHARE_BOUNDARY_YEARS)))

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        for year in dfp_years:
            dfp_path = root / f"dfp_{year}.zip"
            dfp_bytes, dfp_sha = _download(DFP_URL.format(year=year), dfp_path)
            ledger_audit = _audit_dfp_ledger(dfp_path, year)

            record: dict[str, object] = {
                "dataset": "DFP",
                "year": year,
                "bytes": dfp_bytes,
                "sha256": dfp_sha,
                **ledger_audit,
            }
            if bool(ledger_audit["composition_member_present"]):
                dfp, dfp_audit = audit_dfp_composition_capital(dfp_path, year)
                shares = normalize_dfp_shares_outstanding(dfp)
                if shares.empty or (shares["total_outstanding"] < 0).any():
                    raise RuntimeError(f"DFP {year}: invalid normalized shares")
                record.update(
                    {
                        "composition_rows": dfp_audit.rows,
                        "composition_companies": dfp_audit.companies,
                        "composition_missing_available_from": dfp_audit.missing_available_from,
                        "normalized_share_rows": len(shares),
                    }
                )
            elif year in DFP_SHARE_BOUNDARY_YEARS:
                raise RuntimeError(
                    f"DFP {year}: structured capital-composition section expected but absent"
                )
            else:
                record.update(
                    {
                        "composition_rows": None,
                        "composition_companies": None,
                        "composition_missing_available_from": None,
                        "normalized_share_rows": None,
                        "composition_status": "historical_archive_without_structured_section",
                    }
                )
            records.append(record)
            print("CVM_PIT_DFP_BOUNDARY " + json.dumps(record, sort_keys=True))

        for year in FRE_BOUNDARY_YEARS:
            fre_path = root / f"fre_{year}.zip"
            fre_bytes, fre_sha = _download(FRE_URL.format(year=year), fre_path)
            fre, fre_audit = audit_fre_capital_social(fre_path, year)
            if fre.empty:
                raise RuntimeError(f"FRE {year}: empty capital-social section")
            record = {
                "dataset": "FRE",
                "year": year,
                "bytes": fre_bytes,
                "sha256": fre_sha,
                "rows": fre_audit.rows,
                "companies": fre_audit.companies,
                "missing_available_from": fre_audit.missing_available_from,
            }
            records.append(record)
            print("CVM_PIT_FRE_BOUNDARY " + json.dumps(record, sort_keys=True))

    failures = []
    for record in records:
        if record["dataset"] == "FRE" and record["missing_available_from"]:
            failures.append(record)
        if record["dataset"] == "DFP" and record["ledger_missing_receipts"]:
            failures.append(record)
        if (
            record["dataset"] == "DFP"
            and record.get("composition_missing_available_from") not in (None, 0)
        ):
            failures.append(record)
    if failures:
        raise SystemExit("CVM PIT source gate found missing availability timestamps")

    print(
        "CVM_PIT_SOURCE_GATE "
        + json.dumps(
            {
                "dfp_ledger_years": list(DFP_LEDGER_BOUNDARY_YEARS),
                "dfp_share_years": list(DFP_SHARE_BOUNDARY_YEARS),
                "fre_years": list(FRE_BOUNDARY_YEARS),
                "all_passed": True,
                "note": (
                    "official CVM boundary vintages; historical DFP packages may predate "
                    "the 2024 structured capital-composition open-data addition; absence is "
                    "recorded, never replaced by synthetic availability dates"
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

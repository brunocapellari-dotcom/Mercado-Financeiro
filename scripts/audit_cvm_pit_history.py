from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile

from mercado_financeiro.pit import (
    audit_dfp_composition_capital,
    audit_fre_capital_social,
    normalize_dfp_shares_outstanding,
)
from mercado_financeiro.security import DownloadPolicy, RetryPolicy, download_https_with_retry

DFP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
FRE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip"
# Early, middle and recent vintages are live-source boundary checks.  The complete
# 2011-2026 behavioral surface is covered by deterministic tests and the identity
# integration; downloading every full FRE package on every PR would add gigabytes
# of redundant traffic without increasing parser-path coverage.
BOUNDARY_YEARS = (2011, 2018, 2025)
POLICY = DownloadPolicy(max_bytes=1_000_000_000, timeout_seconds=240.0)
RETRY = RetryPolicy(attempts=5, initial_delay_seconds=2.0, max_delay_seconds=20.0)


def _download(url: str, target: Path) -> tuple[int, str]:
    payload = download_https_with_retry(url, POLICY, retry_policy=RETRY)
    target.write_bytes(payload)
    return len(payload), sha256(payload).hexdigest()


def main() -> None:
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for year in BOUNDARY_YEARS:
            dfp_path = root / f"dfp_{year}.zip"
            dfp_bytes, dfp_sha = _download(DFP_URL.format(year=year), dfp_path)
            dfp, dfp_audit = audit_dfp_composition_capital(dfp_path, year)
            shares = normalize_dfp_shares_outstanding(dfp)
            if shares.empty or (shares["total_outstanding"] < 0).any():
                raise RuntimeError(f"DFP {year}: invalid normalized shares")

            fre_path = root / f"fre_{year}.zip"
            fre_bytes, fre_sha = _download(FRE_URL.format(year=year), fre_path)
            fre, fre_audit = audit_fre_capital_social(fre_path, year)
            if fre.empty:
                raise RuntimeError(f"FRE {year}: empty capital-social section")

            record = {
                "year": year,
                "dfp_bytes": dfp_bytes,
                "dfp_sha256": dfp_sha,
                "dfp_rows": dfp_audit.rows,
                "dfp_companies": dfp_audit.companies,
                "dfp_missing_available_from": dfp_audit.missing_available_from,
                "normalized_share_rows": len(shares),
                "fre_bytes": fre_bytes,
                "fre_sha256": fre_sha,
                "fre_rows": fre_audit.rows,
                "fre_companies": fre_audit.companies,
                "fre_missing_available_from": fre_audit.missing_available_from,
            }
            records.append(record)
            print("CVM_PIT_BOUNDARY " + json.dumps(record, sort_keys=True))

    if any(
        record["dfp_missing_available_from"] or record["fre_missing_available_from"]
        for record in records
    ):
        raise SystemExit("CVM PIT source gate found rows without availability timestamps")
    print(
        "CVM_PIT_SOURCE_GATE "
        + json.dumps(
            {
                "years": list(BOUNDARY_YEARS),
                "all_passed": True,
                "note": "official CVM boundary vintages; no synthetic availability dates",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

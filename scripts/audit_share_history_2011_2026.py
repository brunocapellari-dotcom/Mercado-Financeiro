from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import zipfile

from mercado_financeiro.pit import (
    audit_fre_capital_social,
    audit_fre_treasury_last_exercise,
    normalize_fre_issued_shares,
    normalize_fre_treasury_shares,
    reconcile_fre_issued_and_treasury,
)
from mercado_financeiro.security import (
    DownloadPolicy,
    RetryPolicy,
    download_https_with_retry,
)


FRE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip"
POLICY = DownloadPolicy(max_bytes=500_000_000, timeout_seconds=180.0)
RETRY = RetryPolicy(
    attempts=5,
    initial_delay_seconds=2.0,
    max_delay_seconds=20.0,
)


def _download(url: str) -> bytes:
    return download_https_with_retry(url, POLICY, retry_policy=RETRY)


def _members(payload: bytes) -> set[str]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return set(archive.namelist())


def main() -> None:
    annual: list[dict[str, object]] = []
    failed: list[int] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for year in range(2011, 2027):
            payload = _download(FRE_URL.format(year=year))
            digest = sha256(payload).hexdigest()
            path = root / f"fre_{year}.zip"
            path.write_bytes(payload)
            members = _members(payload)

            capital, capital_audit = audit_fre_capital_social(path, year)
            issued = normalize_fre_issued_shares(capital)
            if issued.empty:
                failed.append(year)

            treasury_member = (
                f"fre_cia_aberta_valor_mobiliario_tesouraria_ultimo_exercicio_{year}.csv"
            )
            treasury_member_present = treasury_member in members
            treasury_rows = 0
            treasury_final_rows = 0
            resolved_rows = 0
            ambiguous_rows = 0
            incomplete_rows = 0
            invalid_treasury_groups = 0
            if treasury_member_present:
                treasury_raw, treasury_audit = audit_fre_treasury_last_exercise(path, year)
                treasury = normalize_fre_treasury_shares(treasury_raw)
                reconciled = reconcile_fre_issued_and_treasury(issued, treasury)
                treasury_rows = treasury_audit.rows
                treasury_final_rows = len(treasury)
                if "treasury_status" in treasury.columns:
                    invalid_treasury_groups = int(
                        treasury["treasury_status"].astype(str).ne("valid").sum()
                    )
                resolved_rows = int(
                    reconciled["eligible_for_valuation"].fillna(False).sum()
                )
                ambiguous_rows = int(
                    reconciled["shares_status"]
                    .astype(str)
                    .eq("ambiguous_aggregate_treasury")
                    .sum()
                )
                incomplete_rows = int(
                    reconciled["shares_status"]
                    .astype(str)
                    .isin(
                        [
                            "treasury_class_incomplete",
                            "unsupported_treasury_class",
                            "issued_only_treasury_unavailable",
                            "invalid_treasury_source",
                        ]
                    )
                    .sum()
                )

            record = {
                "year": year,
                "bytes": len(payload),
                "sha256": digest,
                "capital_rows": capital_audit.rows,
                "capital_companies": capital_audit.companies,
                "capital_missing_available_from": capital_audit.missing_available_from,
                "issued_rows": len(issued),
                "issued_issuers": int(issued["issuer_id"].nunique()) if len(issued) else 0,
                "treasury_member_present": treasury_member_present,
                "treasury_rows": treasury_rows,
                "treasury_final_rows": treasury_final_rows,
                "valuation_eligible_rows": resolved_rows,
                "valuation_eligible_ratio": (
                    float(resolved_rows / len(issued)) if len(issued) else 0.0
                ),
                "ambiguous_aggregate_treasury_rows": ambiguous_rows,
                "incomplete_treasury_rows": incomplete_rows,
                "invalid_treasury_groups": invalid_treasury_groups,
            }
            annual.append(record)
            print("FRE_SHARE_YEAR " + json.dumps(record, sort_keys=True))

    summary = {
        "years": annual,
        "failed_source_years": sorted(set(failed)),
        "all_capital_sources_valid": not failed,
        "note": (
            "Capital Emitido is retained PIT for every year. Market-cap eligibility "
            "requires independently reconciled treasury balances; no missing treasury "
            "class is silently assumed to be zero when ON and PN both exist."
        ),
    }
    print("FRE_SHARE_HISTORY_SUMMARY " + json.dumps(summary, sort_keys=True))
    if failed:
        raise SystemExit(
            "FRE issued-capital source unavailable/empty for years: "
            + ",".join(map(str, sorted(set(failed))))
        )


if __name__ == "__main__":
    main()

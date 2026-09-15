from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
import urllib.error

import pandas as pd

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.pit import (
    IdentityGatePolicy,
    audit_fca_ticker_issuer_bridge,
    build_tradable_universe_pit,
    combine_b3_isin_registries,
    combine_fca_ticker_issuer_history,
    enrich_historical_identity_with_b3_emissor,
    enrich_historical_identity_with_registry_history,
    evaluate_identity_gate,
    parse_b3_emissor_zip,
    parse_b3_isin_registry_zip,
)
from mercado_financeiro.security import DownloadPolicy, download_https

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
META_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/"
FILE_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/{token}"
# Official B3 file id 51780 was already referenced by a public brFinance commit
# dated 2022-01-24. The third-party repository is discovery evidence only; bytes
# are downloaded directly from B3 and hashed here before use.
ARCHIVED_B3_FILE_ID = 51780
ARCHIVE_PUBLICLY_OBSERVED_AT = pd.Timestamp("2022-01-24T17:37:59Z")


def _token(file_id: int | str) -> str:
    return base64.b64encode(json.dumps(file_id, separators=(",", ":")).encode()).decode()


def _get(url: str, attempts: int = 5) -> bytes:
    policy = DownloadPolicy(max_bytes=400_000_000, timeout_seconds=180.0)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            payload = download_https(url, policy)
            if not payload:
                raise OSError("official source returned empty response")
            return payload
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            if attempt == attempts:
                break
            delay = min(2**attempt, 20)
            print(f"SOURCE_RETRY attempt={attempt}/{attempts} delay={delay} url={url!r}")
            time.sleep(delay)
    raise RuntimeError(f"official source unavailable after {attempts} attempts: {url}") from last


def _load_fca(root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in range(2010, 2027):
        target = root / f"fca_{year}.zip"
        target.write_bytes(_get(FCA_URL.format(year=year)))
        frame, _ = audit_fca_ticker_issuer_bridge(target, year)
        frames.append(frame)
    return combine_fca_ticker_issuer_history(frames)


def _load_registries() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    meta = json.loads(_get(META_URL))
    current_file_id = meta["geralPt"]["id"]
    current_generated_at = pd.Timestamp(meta["geralPt"]["dataGeracao"])
    current_payload = _get(FILE_URL.format(token=_token(current_file_id)))
    current_digest = sha256(current_payload).hexdigest()
    emissor, _ = parse_b3_emissor_zip(
        current_payload,
        evidence_available_from=current_generated_at,
        source_sha256=current_digest,
    )
    current_exact, _ = parse_b3_isin_registry_zip(
        current_payload,
        evidence_available_from=current_generated_at,
        source_sha256=current_digest,
    )
    current_exact["identity_evidence_source"] = "B3_ISIN_REGISTRY_CURRENT_SNAPSHOT"

    archive_payload = _get(FILE_URL.format(token=_token(ARCHIVED_B3_FILE_ID)))
    archive_digest = sha256(archive_payload).hexdigest()
    archive_exact, archive_audit = parse_b3_isin_registry_zip(
        archive_payload,
        evidence_available_from=ARCHIVE_PUBLICLY_OBSERVED_AT,
        source_sha256=archive_digest,
    )
    archive_exact["identity_evidence_source"] = f"B3_ISIN_ARCHIVE_FILE_{ARCHIVED_B3_FILE_ID}"
    combined = combine_b3_isin_registries([archive_exact, current_exact])
    provenance = {
        "current_file_id": current_file_id,
        "current_generated_at": current_generated_at.isoformat(),
        "current_sha256": current_digest,
        "archive_file_id": ARCHIVED_B3_FILE_ID,
        "archive_publicly_observed_at": ARCHIVE_PUBLICLY_OBSERVED_AT.isoformat(),
        "archive_sha256": archive_digest,
        "archive_valid_security_rows": archive_audit.valid_security_rows,
        "combined_security_rows": len(combined),
    }
    print("B3_IDENTITY_REGISTRY_HISTORY " + json.dumps(provenance, sort_keys=True))
    return emissor, combined, provenance


def main() -> None:
    policy = IdentityGatePolicy()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fca = _load_fca(root)
        emissor, registry_history, registry_provenance = _load_registries()
        annual: list[dict[str, object]] = []
        failed_years: list[int] = []

        for year in range(2011, 2027):
            path = root / f"COTAHIST_A{year}.ZIP"
            path.write_bytes(_get(COTAHIST_URL.format(year=year)))
            quotes, quote_audit = select_regular_share_quotes(read_cotahist(path))
            historical, baseline = build_tradable_universe_pit(
                quotes,
                fca,
                identity_policy="historical_identity",
            )
            prefix, prefix_audit = enrich_historical_identity_with_b3_emissor(historical, emissor)
            exact, exact_audit = enrich_historical_identity_with_registry_history(
                prefix, registry_history
            )
            gate = evaluate_identity_gate(exact, policy)
            if not gate.passed:
                failed_years.append(year)
            annual.append(
                {
                    "year": year,
                    "observations": int(len(exact)),
                    "unique_tickers": int(quote_audit.unique_tickers),
                    "baseline_mapped_row_ratio": float(baseline.mapped_row_ratio),
                    "prefix_mapped_row_ratio": float(prefix_audit.mapped_row_ratio),
                    "prefix_mapped_volume_ratio": float(prefix_audit.mapped_volume_ratio),
                    "prefix_disagreement_rows": int(prefix_audit.conflict_rows),
                    "exact_mapped_row_ratio": float(exact_audit.mapped_row_ratio),
                    "exact_mapped_volume_ratio": float(exact_audit.mapped_volume_ratio),
                    "ambiguous_volume_ratio": float(gate.ambiguous_volume_ratio),
                    "largest_unresolved_volume_ratio": float(gate.largest_unresolved_volume_ratio),
                    "unresolved_securities": int(gate.unresolved_securities),
                    "gate_passed": bool(gate.passed),
                    "gate_reasons": list(gate.reasons),
                }
            )
            print("IDENTITY_YEAR " + json.dumps(annual[-1], sort_keys=True))

        summary = {
            "registry_provenance": registry_provenance,
            "policy": {
                "min_mapped_volume_ratio": policy.min_mapped_volume_ratio,
                "min_mapped_row_ratio": policy.min_mapped_row_ratio,
                "max_ambiguous_volume_ratio": policy.max_ambiguous_volume_ratio,
                "max_single_unresolved_volume_ratio": policy.max_single_unresolved_volume_ratio,
            },
            "years": annual,
            "failed_years": failed_years,
            "all_years_passed": not failed_years,
        }
        print("IDENTITY_2011_2026_SUMMARY " + json.dumps(summary, sort_keys=True))
        if failed_years:
            raise SystemExit(
                "historical identity gate failed for years: " + ",".join(map(str, failed_years))
            )


if __name__ == "__main__":
    main()

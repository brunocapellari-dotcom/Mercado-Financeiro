from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import pandas as pd

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.pit import (
    IdentityGatePolicy,
    audit_fca_issuer_name_registry,
    audit_fca_ticker_issuer_bridge,
    build_tradable_universe_pit,
    combine_b3_isin_registries,
    combine_fca_issuer_name_history,
    combine_fca_ticker_issuer_history,
    enrich_historical_identity_with_b3_emissor,
    enrich_historical_identity_with_fca_names,
    enrich_historical_identity_with_registry_history,
    enrich_historical_identity_with_verified_evidence,
    evaluate_identity_gate,
    parse_b3_emissor_zip,
    parse_b3_isin_registry_zip,
    verified_historical_identity_evidence,
)
from mercado_financeiro.security import (
    DownloadPolicy,
    RetryPolicy,
    download_https_with_retry,
    validate_zip_bytes,
)

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
META_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/"
FILE_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/{token}"

ARCHIVED_B3_FILE_ID = 51780
ARCHIVE_PUBLICLY_OBSERVED_AT = pd.Timestamp("2022-01-24T17:37:59Z")
_SOURCE_POLICY = DownloadPolicy(max_bytes=400_000_000, timeout_seconds=180.0)


def _token(file_id: int | str) -> str:
    return base64.b64encode(json.dumps(file_id, separators=(",", ":")).encode()).decode()


def _require_zip_payload(payload: bytes) -> None:
    if not payload.startswith(b"PK"):
        raise OSError("official source returned a non-ZIP payload")
    validate_zip_bytes(payload)


def _get(url: str, attempts: int = 5, *, require_zip: bool = False) -> bytes:
    return download_https_with_retry(
        url,
        _SOURCE_POLICY,
        retry_policy=RetryPolicy(
            attempts=attempts,
            initial_delay_seconds=2.0,
            max_delay_seconds=20.0,
        ),
        payload_validator=_require_zip_payload if require_zip else None,
    )

def _load_fca(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ticker_frames: list[pd.DataFrame] = []
    name_frames: list[pd.DataFrame] = []
    for year in range(2010, 2027):
        target = root / f"fca_{year}.zip"
        target.write_bytes(_get(FCA_URL.format(year=year), require_zip=True))
        ticker_frame, ticker_audit = audit_fca_ticker_issuer_bridge(target, year)
        ticker_frames.append(ticker_frame)

        try:
            name_frame, name_audit = audit_fca_issuer_name_registry(target, year)
        except ValueError as exc:
            print(
                "FCA_NAME_VINTAGE_EXCLUDED "
                + json.dumps({"year": year, "reason": str(exc)}, sort_keys=True)
            )
            name_rows = 0
            name_issuers = 0
        else:
            if not name_frame.empty:
                name_frames.append(name_frame)
            name_rows = name_audit.name_rows
            name_issuers = name_audit.unique_issuers

        print(
            "FCA_IDENTITY_SOURCE "
            + json.dumps(
                {
                    "year": year,
                    "ticker_rows": ticker_audit.normalized_rows,
                    "ticker_invalid_rows": ticker_audit.invalid_ticker_rows,
                    "name_rows": name_rows,
                    "name_issuers": name_issuers,
                },
                sort_keys=True,
            )
        )
    if not name_frames:
        raise RuntimeError("no ledger-linked FCA issuer-name vintages were usable")
    return (
        combine_fca_ticker_issuer_history(ticker_frames),
        combine_fca_issuer_name_history(name_frames),
    )


def _load_registries() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    meta = json.loads(_get(META_URL))
    current_file_id = meta["geralPt"]["id"]
    current_generated_at = pd.Timestamp(meta["geralPt"]["dataGeracao"])
    current_payload = _get(FILE_URL.format(token=_token(current_file_id)), require_zip=True)
    current_digest = sha256(current_payload).hexdigest()
    emissor, emissor_audit = parse_b3_emissor_zip(
        current_payload,
        evidence_available_from=current_generated_at,
        source_sha256=current_digest,
    )
    current_exact, current_audit = parse_b3_isin_registry_zip(
        current_payload,
        evidence_available_from=current_generated_at,
        source_sha256=current_digest,
    )
    current_exact["identity_evidence_source"] = "B3_ISIN_REGISTRY_CURRENT_SNAPSHOT"

    registries = [current_exact]
    archive_provenance: dict[str, object] = {
        "archive_file_id": ARCHIVED_B3_FILE_ID,
        "archive_publicly_observed_at": ARCHIVE_PUBLICLY_OBSERVED_AT.isoformat(),
        "archive_available": False,
    }
    try:
        archive_payload = _get(FILE_URL.format(token=_token(ARCHIVED_B3_FILE_ID)), attempts=1, require_zip=True)
    except RuntimeError as exc:
        print(
            "B3_ARCHIVE_UNAVAILABLE "
            + json.dumps(
                {
                    "file_id": ARCHIVED_B3_FILE_ID,
                    "reason": str(exc),
                    "action": "continue_with_current_b3_and_cvm_identity_sources",
                },
                sort_keys=True,
            )
        )
    else:
        archive_digest = sha256(archive_payload).hexdigest()
        archive_exact, archive_audit = parse_b3_isin_registry_zip(
            archive_payload,
            evidence_available_from=ARCHIVE_PUBLICLY_OBSERVED_AT,
            source_sha256=archive_digest,
        )
        archive_exact["identity_evidence_source"] = (
            f"B3_ISIN_ARCHIVE_FILE_{ARCHIVED_B3_FILE_ID}"
        )
        registries.append(archive_exact)
        archive_provenance.update(
            {
                "archive_available": True,
                "archive_sha256": archive_digest,
                "archive_valid_security_rows": archive_audit.valid_security_rows,
            }
        )

    combined = combine_b3_isin_registries(registries)
    provenance = {
        "current_file_id": current_file_id,
        "current_generated_at": current_generated_at.isoformat(),
        "current_sha256": current_digest,
        "current_valid_security_rows": current_audit.valid_security_rows,
        "current_valid_issuers": current_audit.valid_issuers,
        "emissor_valid_rows": emissor_audit.valid_rows,
        "combined_security_rows": len(combined),
        **archive_provenance,
    }
    print("B3_IDENTITY_REGISTRY_HISTORY " + json.dumps(provenance, sort_keys=True))
    return emissor, combined, provenance


def _top_unresolved(frame: pd.DataFrame, limit: int = 15) -> list[dict[str, object]]:
    unresolved = frame.loc[~frame["identity_mapping_status"].eq("resolved")].copy()
    if unresolved.empty:
        return []
    grouped = (
        unresolved.groupby(["ticker", "security_id", "issuer_short_name"], dropna=False)
        .agg(
            observations=("trade_date", "size"),
            volume=("financial_volume", "sum"),
            first_date=("trade_date", "min"),
            last_date=("trade_date", "max"),
        )
        .reset_index()
        .sort_values("volume", ascending=False)
        .head(limit)
    )
    grouped["first_date"] = grouped["first_date"].astype(str)
    grouped["last_date"] = grouped["last_date"].astype(str)
    return grouped.to_dict(orient="records")


def main() -> None:
    policy = IdentityGatePolicy()
    verified_evidence = verified_historical_identity_evidence()
    print(
        "VERIFIED_IDENTITY_EVIDENCE "
        + json.dumps(
            {
                "rows": len(verified_evidence),
                "security_ids": sorted(verified_evidence["security_id"].astype(str).tolist()),
                "source": "reviewed official CVM document pairs; static identity only",
            },
            sort_keys=True,
        )
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fca_ticker, fca_names = _load_fca(root)
        emissor, registry_history, registry_provenance = _load_registries()
        annual: list[dict[str, object]] = []
        failed_years: list[int] = []

        for year in range(2011, 2027):
            path = root / f"COTAHIST_A{year}.ZIP"
            path.write_bytes(_get(COTAHIST_URL.format(year=year), require_zip=True))
            quotes, quote_audit = select_regular_share_quotes(read_cotahist(path))

            historical, baseline = build_tradable_universe_pit(
                quotes,
                fca_ticker,
                identity_policy="historical_identity",
            )
            prefix, prefix_audit = enrich_historical_identity_with_b3_emissor(
                historical, emissor
            )
            exact, exact_audit = enrich_historical_identity_with_registry_history(
                prefix, registry_history
            )
            named, name_audit = enrich_historical_identity_with_fca_names(exact, fca_names)
            verified, verified_audit = enrich_historical_identity_with_verified_evidence(
                named, verified_evidence
            )
            gate = evaluate_identity_gate(verified, policy)
            if not gate.passed:
                failed_years.append(year)

            record = {
                "year": year,
                "observations": int(len(verified)),
                "unique_tickers": int(quote_audit.unique_tickers),
                "baseline_mapped_row_ratio": float(baseline.mapped_row_ratio),
                "prefix_mapped_row_ratio": float(prefix_audit.mapped_row_ratio),
                "prefix_mapped_volume_ratio": float(prefix_audit.mapped_volume_ratio),
                "prefix_disagreement_rows": int(prefix_audit.conflict_rows),
                "exact_mapped_row_ratio": float(exact_audit.mapped_row_ratio),
                "exact_mapped_volume_ratio": float(exact_audit.mapped_volume_ratio),
                "exact_newly_resolved_rows": int(exact_audit.newly_resolved_rows),
                "name_mapped_row_ratio": float(name_audit.mapped_row_ratio),
                "name_mapped_volume_ratio": float(name_audit.mapped_volume_ratio),
                "name_newly_resolved_rows": int(name_audit.newly_resolved_rows),
                "name_ambiguous_short_names": int(name_audit.ambiguous_short_names),
                "verified_mapped_row_ratio": float(verified_audit.mapped_row_ratio),
                "verified_mapped_volume_ratio": float(verified_audit.mapped_volume_ratio),
                "verified_newly_resolved_rows": int(verified_audit.newly_resolved_rows),
                "verified_disagreement_rows": int(verified_audit.disagreement_rows),
                "ambiguous_volume_ratio": float(gate.ambiguous_volume_ratio),
                "largest_unresolved_volume_ratio": float(gate.largest_unresolved_volume_ratio),
                "unresolved_securities": int(gate.unresolved_securities),
                "gate_passed": bool(gate.passed),
                "gate_reasons": list(gate.reasons),
            }
            annual.append(record)
            print("IDENTITY_YEAR " + json.dumps(record, sort_keys=True))
            if not gate.passed:
                print(
                    "IDENTITY_UNRESOLVED_TOP "
                    + json.dumps(
                        {"year": year, "values": _top_unresolved(verified)},
                        sort_keys=True,
                    )
                )

        summary = {
            "registry_provenance": registry_provenance,
            "verified_identity_rows": len(verified_evidence),
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

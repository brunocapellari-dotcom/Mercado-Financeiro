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
from mercado_financeiro.pit.b3_emissor import (
    enrich_historical_identity_with_b3_emissor,
    parse_b3_emissor_zip,
)
from mercado_financeiro.pit.b3_isin import (
    enrich_historical_identity_with_exact_isin,
    parse_b3_isin_registry_zip,
)
from mercado_financeiro.pit.fca import (
    audit_fca_ticker_issuer_bridge,
    combine_fca_ticker_issuer_history,
)
from mercado_financeiro.pit.universe import build_tradable_universe_pit
from mercado_financeiro.security import DownloadPolicy, download_https

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2011.ZIP"
META_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/"
FILE_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/{token}"


def _get(url: str, attempts: int = 5) -> bytes:
    last_error: Exception | None = None
    policy = DownloadPolicy(max_bytes=300_000_000, timeout_seconds=120.0)
    for attempt in range(1, attempts + 1):
        try:
            payload = download_https(url, policy)
            if not payload:
                raise OSError("official source returned an empty response")
            return payload
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = min(2 ** attempt, 20)
            print(
                "SOURCE_RETRY "
                f"attempt={attempt}/{attempts} delay_seconds={delay} url={url!r} "
                f"error={type(exc).__name__}:{exc}"
            )
            time.sleep(delay)
    raise RuntimeError(f"official source unavailable after {attempts} attempts: {url}") from last_error


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fca_frames = []
        for year in range(2010, 2027):
            target = root / f"fca_{year}.zip"
            target.write_bytes(_get(FCA_URL.format(year=year)))
            frame, _ = audit_fca_ticker_issuer_bridge(target, year)
            fca_frames.append(frame)
        fca_history = combine_fca_ticker_issuer_history(fca_frames)

        cotahist_path = root / "COTAHIST_A2011.ZIP"
        cotahist_path.write_bytes(_get(COTAHIST_URL))
        quotes, quote_audit = select_regular_share_quotes(read_cotahist(cotahist_path))
        historical, baseline = build_tradable_universe_pit(
            quotes, fca_history, identity_policy="historical_identity"
        )
        print(
            "IDENTITY_BASELINE "
            f"rows={baseline.rows} mapped_row_ratio={baseline.mapped_row_ratio:.6f} "
            f"mapped_volume_ratio={baseline.mapped_volume_ratio:.6f} unique_tickers={quote_audit.unique_tickers}"
        )

        meta = json.loads(_get(META_URL))
        file_id = meta["geralPt"]["id"]
        generated_at = pd.Timestamp(meta["geralPt"]["dataGeracao"])
        token = base64.b64encode(json.dumps(file_id, separators=(",", ":")).encode()).decode()
        registry_payload = _get(FILE_URL.format(token=token))
        digest = sha256(registry_payload).hexdigest()

        emissor, emissor_parse = parse_b3_emissor_zip(
            registry_payload,
            evidence_available_from=generated_at,
            source_sha256=digest,
        )
        prefix_enriched, prefix_audit = enrich_historical_identity_with_b3_emissor(
            historical, emissor
        )
        print(
            "IDENTITY_PREFIX_STAGE "
            f"mapped_row_ratio={prefix_audit.mapped_row_ratio:.6f} "
            f"mapped_volume_ratio={prefix_audit.mapped_volume_ratio:.6f} "
            f"conflicts={prefix_audit.conflict_rows} valid_issuers={emissor_parse.valid_rows}"
        )

        registry, registry_audit = parse_b3_isin_registry_zip(
            registry_payload,
            evidence_available_from=generated_at,
            source_sha256=digest,
        )
        exact, exact_audit = enrich_historical_identity_with_exact_isin(
            prefix_enriched, registry
        )
        print(
            "B3_ISIN_REGISTRY "
            f"file_id={file_id} generated_at={generated_at.isoformat()} sha256={digest} "
            f"issuer_rows={registry_audit.issuer_rows} valid_issuers={registry_audit.valid_issuers} "
            f"numbering_rows={registry_audit.numbering_rows} valid_security_rows={registry_audit.valid_security_rows} "
            f"invalid_isin_rows={registry_audit.invalid_isin_rows} missing_issuer_rows={registry_audit.missing_issuer_rows} "
            f"ambiguous_isins={registry_audit.ambiguous_isins}"
        )
        print(
            "IDENTITY_EXACT_ISIN "
            f"rows={exact_audit.rows} resolved_before={exact_audit.resolved_before} "
            f"resolved_after={exact_audit.resolved_after} newly_resolved={exact_audit.newly_resolved_rows} "
            f"overrides_prior_conflict={exact_audit.exact_overrides_prior_conflict_rows} "
            f"ambiguous_registry_rows={exact_audit.ambiguous_registry_rows} "
            f"mapped_row_ratio={exact_audit.mapped_row_ratio:.6f} "
            f"mapped_volume_ratio={exact_audit.mapped_volume_ratio:.6f} "
            f"unique_issuers={exact_audit.unique_issuers}"
        )

        unresolved = exact.loc[exact["identity_mapping_status"] != "resolved"].copy()
        top = (
            unresolved.groupby(["ticker", "security_id", "identity_mapping_status"], as_index=False)
            .agg(
                observations=("trade_date", "size"),
                volume=("financial_volume", "sum"),
                first_date=("trade_date", "min"),
                last_date=("trade_date", "max"),
            )
            .sort_values("volume", ascending=False)
            .head(50)
        )
        print(f"IDENTITY_EXACT_REMAINING_TOP values={top.to_dict(orient='records')}")


if __name__ == "__main__":
    main()

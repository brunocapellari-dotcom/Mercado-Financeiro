from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

import pandas as pd

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.pit.b3_emissor import (
    enrich_historical_identity_with_b3_emissor,
    parse_b3_emissor_zip,
)
from mercado_financeiro.pit.fca import (
    audit_fca_ticker_issuer_bridge,
    combine_fca_ticker_issuer_history,
)
from mercado_financeiro.pit.universe import build_tradable_universe_pit

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2011.ZIP"
META_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/"
FILE_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/{token}"


def _get(url: str, attempts: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 fixed official hosts
                payload = response.read()
            if not payload:
                raise OSError("official source returned an empty response")
            return payload
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
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


def _download(url: str, target: Path) -> None:
    target.write_bytes(_get(url))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fca_frames = []
        for year in range(2010, 2027):
            target = root / f"fca_{year}.zip"
            _download(FCA_URL.format(year=year), target)
            frame, _ = audit_fca_ticker_issuer_bridge(target, year)
            fca_frames.append(frame)
        fca_history = combine_fca_ticker_issuer_history(fca_frames)

        cotahist_path = root / "COTAHIST_A2011.ZIP"
        _download(COTAHIST_URL, cotahist_path)
        quotes, quote_audit = select_regular_share_quotes(read_cotahist(cotahist_path))
        historical, historical_audit = build_tradable_universe_pit(
            quotes, fca_history, identity_policy="historical_identity"
        )
        print(
            "IDENTITY_BASELINE "
            f"rows={historical_audit.rows} mapped_row_ratio={historical_audit.mapped_row_ratio:.6f} "
            f"mapped_volume_ratio={historical_audit.mapped_volume_ratio:.6f} "
            f"unique_tickers={quote_audit.unique_tickers}"
        )

        meta_payload = _get(META_URL)
        meta = json.loads(meta_payload)
        file_id = meta["geralPt"]["id"]
        generated_at = pd.Timestamp(meta["geralPt"]["dataGeracao"])
        token = base64.b64encode(json.dumps(file_id, separators=(",", ":")).encode()).decode()
        emissor_payload = _get(FILE_URL.format(token=token))
        digest = sha256(emissor_payload).hexdigest()
        emissor, emissor_audit = parse_b3_emissor_zip(
            emissor_payload,
            evidence_available_from=generated_at,
            source_sha256=digest,
        )
        print(
            "B3_EMISSOR_PARSE "
            f"file_id={file_id} generated_at={generated_at.isoformat()} sha256={digest} "
            f"rows={emissor_audit.rows} valid_rows={emissor_audit.valid_rows} "
            f"invalid_code_rows={emissor_audit.invalid_code_rows} invalid_cnpj_rows={emissor_audit.invalid_cnpj_rows} "
            f"unique_codes={emissor_audit.unique_issuer_codes} ambiguous_codes={emissor_audit.ambiguous_issuer_codes}"
        )

        enriched, audit = enrich_historical_identity_with_b3_emissor(historical, emissor)
        print(
            "IDENTITY_ENRICHED "
            f"rows={audit.rows} resolved_before={audit.resolved_before} resolved_after={audit.resolved_after} "
            f"newly_resolved_rows={audit.newly_resolved_rows} conflicts={audit.conflict_rows} "
            f"mapped_row_ratio={audit.mapped_row_ratio:.6f} mapped_volume_ratio={audit.mapped_volume_ratio:.6f} "
            f"unique_issuers={audit.unique_issuers}"
        )

        unresolved = enriched.loc[enriched["identity_mapping_status"] != "resolved"].copy()
        top = (
            unresolved.groupby(["ticker", "identity_mapping_status"], as_index=False)
            .agg(
                observations=("trade_date", "size"),
                volume=("financial_volume", "sum"),
                first_date=("trade_date", "min"),
                last_date=("trade_date", "max"),
            )
            .sort_values("volume", ascending=False)
            .head(40)
        )
        print(f"IDENTITY_REMAINING_TOP values={top.to_dict(orient='records')}")


if __name__ == "__main__":
    main()

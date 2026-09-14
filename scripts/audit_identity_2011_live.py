from __future__ import annotations

from pathlib import Path
import tempfile
import urllib.request

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.pit.fca import (
    audit_fca_ticker_issuer_bridge,
    combine_fca_ticker_issuer_history,
)
from mercado_financeiro.pit.universe import build_tradable_universe_pit

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2011.ZIP"


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310: fixed hosts
        with target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)


def _print_audit(label: str, universe, audit) -> None:
    print(
        f"IDENTITY_AUDIT policy={label} rows={audit.rows} mapped_rows={audit.mapped_rows} "
        f"unresolved_rows={audit.unresolved_rows} ambiguous_rows={audit.ambiguous_rows} "
        f"later_evidence_rows={audit.later_identity_evidence_rows} "
        f"mapped_row_ratio={audit.mapped_row_ratio:.6f} "
        f"mapped_volume_ratio={audit.mapped_volume_ratio:.6f} "
        f"unique_securities={audit.unique_securities} unique_issuers={audit.unique_issuers}"
    )
    unresolved = universe.loc[
        universe["identity_mapping_status"] != "resolved"
    ].copy()
    if not unresolved.empty:
        top = (
            unresolved.groupby(["ticker", "identity_mapping_status"], as_index=False)
            .agg(
                observations=("trade_date", "size"),
                volume=("financial_volume", "sum"),
                first_date=("trade_date", "min"),
                last_date=("trade_date", "max"),
            )
            .sort_values("volume", ascending=False)
            .head(25)
        )
        print(f"IDENTITY_UNRESOLVED_TOP policy={label} values={top.to_dict(orient='records')}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fca_frames = []
        for year in range(2010, 2027):
            target = root / f"fca_{year}.zip"
            _download(FCA_URL.format(year=year), target)
            frame, audit = audit_fca_ticker_issuer_bridge(target, year)
            fca_frames.append(frame)
            print(
                f"FCA_BRIDGE_AUDIT year={year} section_rows={audit.section_rows} "
                f"stock_rows={audit.stock_rows} rows_with_ticker={audit.rows_with_ticker} "
                f"normalized_rows={audit.normalized_rows} invalid_ticker_rows={audit.invalid_ticker_rows} "
                f"issuers={audit.issuers} tickers={audit.tickers}"
            )
        fca_history = combine_fca_ticker_issuer_history(fca_frames)

        cotahist_path = root / "COTAHIST_A2011.ZIP"
        _download(COTAHIST_URL, cotahist_path)
        quotes, quote_audit = select_regular_share_quotes(read_cotahist(cotahist_path))
        print(
            f"COTAHIST_IDENTITY_INPUT rows={quote_audit.share_rows} "
            f"unique_tickers={quote_audit.unique_tickers} unique_isins={quote_audit.unique_isins}"
        )

        strict_universe, strict_audit = build_tradable_universe_pit(
            quotes, fca_history, identity_policy="strict_publication"
        )
        _print_audit("strict_publication", strict_universe, strict_audit)

        historical_universe, historical_audit = build_tradable_universe_pit(
            quotes, fca_history, identity_policy="historical_identity"
        )
        _print_audit("historical_identity", historical_universe, historical_audit)


if __name__ == "__main__":
    main()

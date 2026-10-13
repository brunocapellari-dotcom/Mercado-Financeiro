from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.security import DownloadPolicy, RetryPolicy, download_https_with_retry

URL_TEMPLATE = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
YEARS = (2011,)


def _download(year: int, target: Path) -> str:
    url = URL_TEMPLATE.format(year=year)
    payload = download_https_with_retry(
        url,
        DownloadPolicy(max_bytes=400_000_000, timeout_seconds=180.0),
        retry_policy=RetryPolicy(attempts=5, initial_delay_seconds=2.0, max_delay_seconds=20.0),
        headers={"Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8"},
    )
    target.write_bytes(payload)
    return sha256(payload).hexdigest()


def main() -> None:
    for year in YEARS:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / f"COTAHIST_A{year}.ZIP"
            digest = _download(year, target)
            frame = read_cotahist(target)
            shares, audit = select_regular_share_quotes(frame)
            first_date = shares["trade_date"].min()
            last_date = shares["trade_date"].max()
            print(
                "COTAHIST_AUDIT "
                f"year={year} bytes={target.stat().st_size} sha256={digest} "
                f"rows={audit.rows} share_rows={audit.share_rows} "
                f"unique_dates={audit.unique_dates} unique_tickers={audit.unique_tickers} "
                f"unique_isins={audit.unique_isins} missing_isin_rows={audit.missing_isin_rows} "
                f"first_date={first_date.date()} last_date={last_date.date()}"
            )
            sample = shares.loc[
                shares["ticker"].isin(["PETR3", "PETR4", "VALE3"]),
                ["trade_date", "ticker", "isin", "close_price", "bdi_code"],
            ].head(6)
            print(f"COTAHIST_SAMPLE year={year} values={sample.to_dict(orient='records')}")


if __name__ == "__main__":
    main()

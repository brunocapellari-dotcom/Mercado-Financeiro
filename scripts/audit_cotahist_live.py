from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import urllib.request

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes

URL_TEMPLATE = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
YEARS = (2011,)


def _download(year: int, target: Path) -> str:
    url = URL_TEMPLATE.format(year=year)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    digest = sha256()
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310: fixed B3 host
        with target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
    return digest.hexdigest()


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

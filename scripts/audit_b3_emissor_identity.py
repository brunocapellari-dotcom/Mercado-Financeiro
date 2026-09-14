from __future__ import annotations

import base64
import csv
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import tempfile
import urllib.request
import zipfile

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes

META_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/"
FILE_URL = "https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/{token}"
COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2011.ZIP"


def _get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 fixed B3 hosts
        return response.read()


def _emissor_rows(payload: bytes) -> list[list[str]]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = archive.namelist()
        print(f"B3_ISIN_ZIP members={members!r}")
        member = next((name for name in members if Path(name).name.upper() == "EMISSOR.TXT"), None)
        if member is None:
            raise ValueError("EMISSOR.TXT not found")
        with archive.open(member) as raw:
            wrapper = TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.reader(wrapper)
            return [row for row in reader if len(row) >= 3]


def _download_cotahist(target: Path) -> None:
    payload = _get(COTAHIST_URL)
    target.write_bytes(payload)


def main() -> None:
    meta_payload = _get(META_URL)
    meta = json.loads(meta_payload)
    print(f"B3_ISIN_META keys={sorted(meta)} body={json.dumps(meta, ensure_ascii=False)[:2000]}")
    file_id = meta["geralPt"]["id"]
    token = base64.b64encode(json.dumps(file_id, separators=(",", ":")).encode()).decode()
    payload = _get(FILE_URL.format(token=token))
    print(
        f"B3_ISIN_FILE id={file_id} bytes={len(payload)} sha256={sha256(payload).hexdigest()}"
    )
    rows = _emissor_rows(payload)
    print(f"B3_EMISSOR rows={len(rows)} sample={rows[:20]!r}")

    by_key: dict[str, set[str]] = {}
    for row in rows:
        key = row[0].strip().upper()
        cnpj = row[2].strip()
        if key:
            by_key.setdefault(key, set()).add(cnpj)

    duplicate_keys = {key: values for key, values in by_key.items() if len(values) > 1}
    print(
        f"B3_EMISSOR keys={len(by_key)} duplicate_keys={len(duplicate_keys)} "
        f"duplicate_sample={list(duplicate_keys.items())[:20]!r}"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "COTAHIST_A2011.ZIP"
        _download_cotahist(path)
        shares, _ = select_regular_share_quotes(read_cotahist(path))

    tickers = sorted(shares["ticker"].unique())
    exact = [ticker for ticker in tickers if ticker in by_key]
    prefix4 = [ticker for ticker in tickers if ticker[:4] in by_key]
    prefix3 = [ticker for ticker in tickers if ticker[:3] in by_key]
    print(
        f"B3_EMISSOR_2011 unique_tickers={len(tickers)} exact={len(exact)} "
        f"prefix4={len(prefix4)} prefix3={len(prefix3)}"
    )

    targets = [
        "VALE5", "VALE3", "AMBV4", "CSNA3", "RDCD3", "HRTP3", "LAME4", "ELPL4",
        "ALLL3", "MNDL4", "DASA3", "CTIP3", "TNLP4", "AEDU3", "CRUZ3", "BISA3",
        "TAMM4", "VIVO4", "TLPP4", "TCSL4", "KLBN4", "MPXE3", "UGPA4", "TBLE3", "SUZB5",
    ]
    for ticker in targets:
        candidates = []
        for key in (ticker, ticker[:4], ticker[:3]):
            if key in by_key:
                candidates.append((key, sorted(by_key[key])))
        print(f"B3_EMISSOR_TARGET ticker={ticker} candidates={candidates!r}")

    unresolved_prefix4 = [ticker for ticker in tickers if ticker[:4] not in by_key]
    print(f"B3_EMISSOR_UNRESOLVED_PREFIX4 count={len(unresolved_prefix4)} sample={unresolved_prefix4[:200]!r}")


if __name__ == "__main__":
    main()

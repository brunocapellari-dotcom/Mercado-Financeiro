from __future__ import annotations

from collections import Counter
from io import BytesIO
import re
import urllib.request
import zipfile

import pandas as pd

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
YEARS = range(2018, 2027)
SIMPLE_SHARE = re.compile(r"^[A-Z]{4}0?[3-8]$")
TOKEN = re.compile(r"[A-Z]{4}0?[3-8]")


def _download(year: int) -> bytes:
    request = urllib.request.Request(
        BASE_URL.format(year=year),
        headers={"User-Agent": "Mercado-Financeiro-PIT-Audit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310: fixed CVM host
        return response.read()


def _read_section(payload: bytes, year: int) -> pd.DataFrame:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        member = f"fca_cia_aberta_valor_mobiliario_{year}.csv"
        with archive.open(member) as source:
            return pd.read_csv(source, sep=";", encoding="latin-1", dtype=str)


def main() -> None:
    global_invalid = Counter()
    for year in YEARS:
        frame = _read_section(_download(year), year)
        stock = frame.loc[
            frame["Valor_Mobiliario"].isin(["Ações Ordinárias", "Ações Preferenciais"])
        ].copy()
        stock["raw"] = stock["Codigo_Negociacao"].fillna("").str.strip().str.upper()
        with_code = stock.loc[stock["raw"].ne("")].copy()
        invalid = with_code.loc[~with_code["raw"].str.fullmatch(SIMPLE_SHARE)].copy()
        global_invalid.update(invalid["raw"].tolist())

        print(
            "FCA_INVALID_SUMMARY "
            f"year={year} stock_rows={len(stock)} with_code={len(with_code)} "
            f"simple_share={len(with_code) - len(invalid)} invalid={len(invalid)} "
            f"unique_invalid={invalid['raw'].nunique()}"
        )
        if invalid.empty:
            continue

        grouped = (
            invalid.groupby(
                [
                    "raw",
                    "Valor_Mobiliario",
                    "CNPJ_Companhia",
                    "Nome_Empresarial",
                    "Sigla_Classe_Acao_Preferencial",
                ],
                dropna=False,
                as_index=False,
            )
            .size()
            .sort_values(["size", "raw"], ascending=[False, True])
            .head(100)
        )
        for row in grouped.itertuples(index=False):
            tokens = TOKEN.findall(row.raw)
            print(
                "FCA_INVALID_VALUE "
                f"year={year} raw={row.raw!r} tokens={tokens!r} "
                f"type={row.Valor_Mobiliario!r} pref={row.Sigla_Classe_Acao_Preferencial!r} "
                f"cnpj={row.CNPJ_Companhia!r} company={row.Nome_Empresarial!r} count={row.size}"
            )

    print("FCA_INVALID_GLOBAL_TOP_START")
    for raw, count in global_invalid.most_common(200):
        print(f"FCA_INVALID_GLOBAL raw={raw!r} count={count} tokens={TOKEN.findall(raw)!r}")
    print("FCA_INVALID_GLOBAL_TOP_END")


if __name__ == "__main__":
    main()

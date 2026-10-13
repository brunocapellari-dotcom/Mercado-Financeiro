from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from mercado_financeiro.pit.fca import (
    audit_fca_ticker_issuer_bridge,
    combine_fca_ticker_issuer_history,
    normalize_fca_share_ticker,
)


def _write_fca_package(path: Path, year: int = 2019) -> None:
    ledger = pd.DataFrame(
        [
            {
                "CNPJ_CIA": "00.000.001/0001-00",
                "DT_REFER": f"{year}-01-01",
                "VERSAO": "2",
                "DENOM_CIA": "CIA TESTE",
                "CD_CVM": "000001",
                "CATEG_DOC": "Categoria A",
                "ID_DOC": "200",
                "DT_RECEB": f"{year}-04-10",
                "LINK_DOC": "https://example.invalid/200",
            }
        ]
    )
    securities = pd.DataFrame(
        [
            {
                "CNPJ_Companhia": "00.000.001/0001-00",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "2",
                "ID_Documento": "200",
                "Nome_Empresarial": "CIA TESTE",
                "Valor_Mobiliario": "Ações Ordinárias",
                "Sigla_Classe_Acao_Preferencial": "",
                "Classe_Acao_Preferencial": "",
                "Codigo_Negociacao": "TEST03",
                "Composicao_BDR_Unit": "",
                "Mercado": "Bolsa",
                "Sigla_Entidade_Administradora": "B3",
                "Entidade_Administradora": "B3 S.A.",
                "Data_Inicio_Negociacao": "2010-02-01",
                "Data_Fim_Negociacao": "",
                "Segmento": "Novo Mercado",
                "Data_Inicio_Listagem": "2010-02-01",
                "Data_Fim_Listagem": "",
            },
            {
                "CNPJ_Companhia": "00.000.001/0001-00",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "2",
                "ID_Documento": "200",
                "Nome_Empresarial": "CIA TESTE",
                "Valor_Mobiliario": "Ações Preferenciais",
                "Sigla_Classe_Acao_Preferencial": "A",
                "Classe_Acao_Preferencial": "Preferencial A",
                "Codigo_Negociacao": "TEST04",
                "Composicao_BDR_Unit": "",
                "Mercado": "Bolsa",
                "Sigla_Entidade_Administradora": "B3",
                "Entidade_Administradora": "B3 S.A.",
                "Data_Inicio_Negociacao": "2010-02-01",
                "Data_Fim_Negociacao": "2019-06-30",
                "Segmento": "Nível 2",
                "Data_Inicio_Listagem": "2010-02-01",
                "Data_Fim_Listagem": "2019-06-30",
            },
            {
                "CNPJ_Companhia": "00.000.001/0001-00",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "2",
                "ID_Documento": "200",
                "Nome_Empresarial": "CIA TESTE",
                "Valor_Mobiliario": "Units",
                "Sigla_Classe_Acao_Preferencial": "",
                "Classe_Acao_Preferencial": "",
                "Codigo_Negociacao": "TEST11",
                "Composicao_BDR_Unit": "1 ON + 2 PN",
                "Mercado": "Bolsa",
                "Sigla_Entidade_Administradora": "B3",
                "Entidade_Administradora": "B3 S.A.",
                "Data_Inicio_Negociacao": "2010-02-01",
                "Data_Fim_Negociacao": "",
                "Segmento": "Nível 2",
                "Data_Inicio_Listagem": "2010-02-01",
                "Data_Fim_Listagem": "",
            },
        ]
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"fca_cia_aberta_{year}.csv",
            ledger.to_csv(index=False, sep=";").encode("latin-1"),
        )
        archive.writestr(
            f"fca_cia_aberta_valor_mobiliario_{year}.csv",
            securities.to_csv(index=False, sep=";").encode("latin-1"),
        )


def test_normalize_fca_share_ticker_accepts_observed_b3_shapes_and_rejects_junk():
    assert normalize_fca_share_ticker("BSLI03", "ordinary") == "BSLI3"
    assert normalize_fca_share_ticker("BRSR06", "preferred") == "BRSR6"
    assert normalize_fca_share_ticker("PETR4", "preferred") == "PETR4"
    assert normalize_fca_share_ticker("B3SA3", "ordinary") == "B3SA3"
    assert normalize_fca_share_ticker("CAL4", "preferred") == "CAL4"
    assert normalize_fca_share_ticker("EQMA3B", "ordinary") == "EQMA3B"
    assert normalize_fca_share_ticker("GOLL54", "preferred") == "GOLL54"
    assert normalize_fca_share_ticker("BRGE11", "preferred") == "BRGE11"
    for junk in ("INVALID", "NÃO", "NÃO HÁ", "00", "000000", "5.4", "5,4", "SJOS"):
        assert normalize_fca_share_ticker(junk, "ordinary") is None


def test_fca_bridge_joins_exact_submission_and_keeps_reported_trading_interval(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_package(package)

    bridge, audit = audit_fca_ticker_issuer_bridge(package, 2019)

    assert set(bridge["ticker"]) == {"TEST3", "TEST4"}
    assert set(bridge["share_class"]) == {"ordinary", "preferred"}
    assert bridge["issuer_id"].nunique() == 1
    assert set(bridge["available_from"]) == {pd.Timestamp("2019-04-10")}
    assert set(bridge["valid_from"]) == {pd.Timestamp("2010-02-01")}
    pref = bridge.loc[bridge["share_class"] == "preferred"].iloc[0]
    assert pref["valid_to_exclusive"] == pd.Timestamp("2019-07-01")
    assert audit.section_rows == 3
    assert audit.stock_rows == 2
    assert audit.normalized_rows == 2
    assert audit.invalid_ticker_rows == 0


def test_fca_bridge_fails_when_represented_version_has_no_ledger_receipt(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_package(package)

    raw = package.read_bytes()
    with zipfile.ZipFile(BytesIO(raw)) as source:
        ledger = pd.read_csv(source.open("fca_cia_aberta_2019.csv"), sep=";", dtype=str)
        securities = source.read("fca_cia_aberta_valor_mobiliario_2019.csv")

    ledger["ID_DOC"] = "999"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as target:
        target.writestr(
            "fca_cia_aberta_2019.csv",
            ledger.to_csv(index=False, sep=";").encode("latin-1"),
        )
        target.writestr("fca_cia_aberta_valor_mobiliario_2019.csv", securities)

    with pytest.raises(ValueError, match="lack available_from"):
        audit_fca_ticker_issuer_bridge(package, 2019)


def test_combine_bridge_retains_distinct_publication_vintages(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_package(package)
    first, _ = audit_fca_ticker_issuer_bridge(package, 2019)
    second = first.copy()
    second["reference_date"] = pd.Timestamp("2020-01-01")
    second["available_from"] = pd.Timestamp("2020-03-01")
    second["evidence_document_id"] = "300"

    combined = combine_fca_ticker_issuer_history([first, second])

    assert len(combined) == 4
    assert combined["reference_date"].nunique() == 2
    assert combined["available_from"].max() == pd.Timestamp("2020-03-01")

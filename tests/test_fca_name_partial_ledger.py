from pathlib import Path
import zipfile

import pandas as pd

from mercado_financeiro.pit import audit_fca_issuer_name_registry


def test_unmatched_general_row_is_excluded_without_discarding_valid_vintage(tmp_path: Path):
    year = 2020
    ledger = pd.DataFrame(
        [
            {
                "CNPJ_CIA": "33.000.167/0001-01",
                "DT_REFER": f"{year}-01-01",
                "VERSAO": "1",
                "DENOM_CIA": "PETROLEO BRASILEIRO S A PETROBRAS",
                "ID_DOC": "100",
                "DT_RECEB": f"{year}-03-01",
            }
        ]
    )
    general = pd.DataFrame(
        [
            {
                "CNPJ_Companhia": "33.000.167/0001-01",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "1",
                "ID_Documento": "100",
                "Nome_Empresarial": "PETROLEO BRASILEIRO S A PETROBRAS",
            },
            {
                "CNPJ_Companhia": "33.592.510/0001-54",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "9",
                "ID_Documento": "MISSING",
                "Nome_Empresarial": "SEM LEDGER",
            },
        ]
    )
    path = tmp_path / "fca.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"fca_cia_aberta_{year}.csv",
            ledger.to_csv(index=False, sep=";").encode("latin-1"),
        )
        archive.writestr(
            f"fca_cia_aberta_geral_{year}.csv",
            general.to_csv(index=False, sep=";").encode("latin-1"),
        )

    registry, audit = audit_fca_issuer_name_registry(path, year)
    assert audit.section_rows == 2
    assert audit.missing_available_from == 1
    assert registry["issuer_id"].nunique() == 1
    assert set(registry["issuer_id"]) == {"33.000.167/0001-01"}
    assert "SEM LEDGER" not in set(registry["company_name_normalized"])

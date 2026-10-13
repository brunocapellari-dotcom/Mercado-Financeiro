import pandas as pd
import pytest

from mercado_financeiro.pit.accounting_normalization import (
    CVMStatementSchema,
    normalize_cvm_statement_rows,
)


SCHEMA = CVMStatementSchema(
    issuer="cnpj",
    account_code="conta",
    account_name="descricao",
    value="valor",
    reference_date="referencia",
    available_from="disponivel",
    filing_version="versao",
)


def test_cvm_statement_normalization_preserves_raw_account_and_maps_only_exact_metric():
    frame = pd.DataFrame(
        {
            "cnpj": ["00.000.000/0001-00", "00.000.000/0001-00"],
            "conta": ["3.01", "3.99"],
            "descricao": ["Receita", "Linha especifica"],
            "valor": ["1.234,50", "50,00"],
            "referencia": ["2026-06-30", "2026-06-30"],
            "disponivel": ["2026-08-10", "2026-08-10"],
            "versao": [1, 1],
        }
    )
    out = normalize_cvm_statement_rows(frame, schema=SCHEMA, statement_name="DRE")
    assert out.loc[out["account_code"].eq("3.01"), "metric"].iloc[0] == "net_revenue"
    assert pd.isna(out.loc[out["account_code"].eq("3.99"), "metric"].iloc[0])
    assert out.loc[0, "accounting_basis"] == "CPC_IFRS_CVM"
    assert out.loc[out["account_code"].eq("3.01"), "value"].iloc[0] == 1234.5


def test_cvm_statement_normalization_blocks_impossible_availability():
    frame = pd.DataFrame(
        {
            "cnpj": ["00.000.000/0001-00"],
            "conta": ["3.01"],
            "descricao": ["Receita"],
            "valor": [100.0],
            "referencia": ["2026-06-30"],
            "disponivel": ["2026-05-01"],
            "versao": [1],
        }
    )
    with pytest.raises(ValueError, match="available before"):
        normalize_cvm_statement_rows(frame, schema=SCHEMA, statement_name="DRE")

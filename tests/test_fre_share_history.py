from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd

from mercado_financeiro.pit import (
    audit_fre_capital_social,
    audit_fre_treasury_last_exercise,
    combine_share_histories,
    normalize_dfp_shares_outstanding,
    normalize_fre_issued_shares,
    normalize_fre_treasury_shares,
    reconcile_fre_issued_and_treasury,
    shares_outstanding_asof,
)


def _capital(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "CNPJ_Companhia": "00.000.000/0001-91",
        "Data_Referencia": "2011-12-31",
        "Versao": "1",
        "ID_Documento": "101",
        "available_from": "2012-03-15",
        "Tipo_Capital": "Capital Emitido",
        "Quantidade_Acoes_Ordinarias": "100",
        "Quantidade_Acoes_Preferenciais": "50",
        "Quantidade_Total_Acoes": "150",
        "Data_Autorizacao_Aprovacao": "2011-12-20",
    }
    row.update(overrides)
    return row


def _treasury(share_class: str, count: int) -> dict[str, object]:
    return {
        "CNPJ_Companhia": "00.000.000/0001-91",
        "Data_Referencia": "2011-12-31",
        "Versao": "1",
        "ID_Documento": "101",
        "available_from": "2012-03-15",
        "Classe_Valor_Mobiliario": share_class,
        "Historico_Exercicio": "Saldo final",
        "Quantidade_Acoes_Tesouraria": str(count),
    }


def test_fre_capital_keeps_approval_as_metadata_and_blocks_valuation_without_treasury():
    issued = normalize_fre_issued_shares(pd.DataFrame([_capital()]))
    assert issued.loc[0, "ordinary_issued"] == 100
    assert issued.loc[0, "preferred_issued"] == 50
    assert issued.loc[0, "total_issued"] == 150
    assert issued.loc[0, "capital_approval_date"] == pd.Timestamp("2011-12-20")
    assert issued.loc[0, "available_from"] == pd.Timestamp("2012-03-15")
    assert not bool(issued.loc[0, "eligible_for_valuation"])
    assert issued.loc[0, "shares_status"] == "issued_only_treasury_unresolved"


def test_fre_capital_derives_one_missing_class_only_from_reported_total():
    issued = normalize_fre_issued_shares(
        pd.DataFrame(
            [
                _capital(
                    Quantidade_Acoes_Preferenciais="",
                    Quantidade_Total_Acoes="150",
                )
            ]
        )
    )
    assert issued.loc[0, "preferred_issued"] == 50


def test_fre_reconciliation_resolves_explicit_on_and_pn_treasury():
    issued = normalize_fre_issued_shares(pd.DataFrame([_capital()]))
    treasury = normalize_fre_treasury_shares(
        pd.DataFrame(
            [
                _treasury("Ação Ordinária", 10),
                _treasury("Ação Preferencial", 5),
            ]
        )
    )
    reconciled = reconcile_fre_issued_and_treasury(issued, treasury)
    assert reconciled.loc[0, "ordinary_outstanding"] == 90
    assert reconciled.loc[0, "preferred_outstanding"] == 45
    assert reconciled.loc[0, "total_outstanding"] == 135
    assert bool(reconciled.loc[0, "eligible_for_valuation"])


def test_fre_aggregate_treasury_fails_closed_for_two_nonzero_share_classes():
    issued = normalize_fre_issued_shares(pd.DataFrame([_capital()]))
    treasury = normalize_fre_treasury_shares(pd.DataFrame([_treasury("Ação", 10)]))
    reconciled = reconcile_fre_issued_and_treasury(issued, treasury)
    assert not bool(reconciled.loc[0, "eligible_for_valuation"])
    assert reconciled.loc[0, "shares_status"] == "ambiguous_aggregate_treasury"


def test_fre_zero_aggregate_treasury_proves_zero_for_both_classes():
    issued = normalize_fre_issued_shares(pd.DataFrame([_capital()]))
    treasury = normalize_fre_treasury_shares(pd.DataFrame([_treasury("Ação", 0)]))
    reconciled = reconcile_fre_issued_and_treasury(issued, treasury)
    assert reconciled.loc[0, "ordinary_treasury"] == 0
    assert reconciled.loc[0, "preferred_treasury"] == 0
    assert bool(reconciled.loc[0, "eligible_for_valuation"])


def test_combined_history_uses_latest_reference_and_dfp_priority_only_as_tiebreaker():
    fre_issued = normalize_fre_issued_shares(
        pd.DataFrame(
            [
                _capital(
                    Data_Referencia="2024-12-31",
                    available_from="2025-03-15",
                    Quantidade_Acoes_Preferenciais="0",
                    Quantidade_Total_Acoes="100",
                )
            ]
        )
    )
    fre_treasury = normalize_fre_treasury_shares(
        pd.DataFrame(
            [
                {
                    **_treasury("Ação", 0),
                    "Data_Referencia": "2024-12-31",
                    "available_from": "2025-03-15",
                }
            ]
        )
    )
    fre = reconcile_fre_issued_and_treasury(fre_issued, fre_treasury)

    dfp_raw = pd.DataFrame(
        [
            {
                "CNPJ_CIA": "00.000.000/0001-91",
                "DT_REFER": "2023-12-31",
                "VERSAO": "1",
                "available_from": "2024-03-15",
                "QT_ACAO_ORDIN_CAP_INTEGR": "90",
                "QT_ACAO_PREF_CAP_INTEGR": "0",
                "QT_ACAO_TOTAL_CAP_INTEGR": "90",
                "QT_ACAO_ORDIN_TESOURO": "0",
                "QT_ACAO_PREF_TESOURO": "0",
                "QT_ACAO_TOTAL_TESOURO": "0",
            }
        ]
    )
    dfp = normalize_dfp_shares_outstanding(dfp_raw)
    combined = combine_share_histories(dfp, fre)
    asof = shares_outstanding_asof(combined, "2025-06-30")
    assert asof.loc[0, "reference_date"] == pd.Timestamp("2024-12-31")
    assert asof.loc[0, "total_outstanding"] == 100
    assert asof.loc[0, "source"].startswith("CVM_FRE")


def test_fre_sections_are_linked_to_exact_document_receipt(tmp_path: Path):
    package = tmp_path / "fre.zip"
    ledger = pd.DataFrame(
        [
            {
                "CNPJ_CIA": "00.000.000/0001-91",
                "DT_REFER": "2011-12-31",
                "VERSAO": "1",
                "ID_DOC": "101",
                "DT_RECEB": "2012-03-15",
            }
        ]
    )
    capital = pd.DataFrame([_capital()]).drop(columns=["available_from"])
    treasury = pd.DataFrame([_treasury("Ação", 0)]).drop(columns=["available_from"])
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "fre_cia_aberta_2011.csv",
            ledger.to_csv(index=False, sep=";").encode("latin-1"),
        )
        archive.writestr(
            "fre_cia_aberta_capital_social_2011.csv",
            capital.to_csv(index=False, sep=";").encode("latin-1"),
        )
        archive.writestr(
            "fre_cia_aberta_valor_mobiliario_tesouraria_ultimo_exercicio_2011.csv",
            treasury.to_csv(index=False, sep=";").encode("latin-1"),
        )

    capital_out, capital_audit = audit_fre_capital_social(package, 2011)
    treasury_out, treasury_audit = audit_fre_treasury_last_exercise(package, 2011)
    assert capital_audit.missing_available_from == 0
    assert treasury_audit.missing_available_from == 0
    assert capital_out.loc[0, "available_from"] == pd.Timestamp("2012-03-15")
    assert treasury_out.loc[0, "available_from"] == pd.Timestamp("2012-03-15")

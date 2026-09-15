from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd

from mercado_financeiro.pit.fca_name import (
    audit_fca_issuer_name_registry,
    enrich_historical_identity_with_fca_names,
    normalize_company_name,
    resolve_fca_name_identity,
)


def _write_fca_name_package(path: Path, year: int = 2022) -> None:
    ledger = pd.DataFrame(
        [
            {
                "CNPJ_CIA": "30.306.294/0001-45",
                "DT_REFER": f"{year}-01-01",
                "VERSAO": "1",
                "DENOM_CIA": "ENEVA S.A.",
                "ID_DOC": "100",
                "DT_RECEB": f"{year}-03-15",
            },
            {
                "CNPJ_CIA": "02.421.421/0001-11",
                "DT_REFER": f"{year}-01-01",
                "VERSAO": "1",
                "DENOM_CIA": "ALL - AMERICA LATINA LOGISTICA S.A.",
                "ID_DOC": "101",
                "DT_RECEB": f"{year}-03-16",
            },
        ]
    )
    general = pd.DataFrame(
        [
            {
                "CNPJ_Companhia": "30.306.294/0001-45",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "1",
                "ID_Documento": "100",
                "Nome_Empresarial": "ENEVA S.A.",
                "Nome_Empresarial_Anterior": "MPX ENERGIA S.A.",
            },
            {
                "CNPJ_Companhia": "02.421.421/0001-11",
                "Data_Referencia": f"{year}-01-01",
                "Versao": "1",
                "ID_Documento": "101",
                "Nome_Empresarial": "RUMO MALHA NORTE S.A.",
                "Nome_Empresarial_Anterior": "ALL - AMERICA LATINA LOGISTICA S.A.",
            },
        ]
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"fca_cia_aberta_{year}.csv",
            ledger.to_csv(index=False, sep=";").encode("latin-1"),
        )
        archive.writestr(
            f"fca_cia_aberta_geral_{year}.csv",
            general.to_csv(index=False, sep=";").encode("latin-1"),
        )


def test_company_name_normalization_removes_legal_noise_but_keeps_identity_tokens():
    assert normalize_company_name("ALL - América Latina Logística S.A.") == "ALL AMERICA LATINA LOGISTICA"
    assert normalize_company_name("MPX Energia S.A.") == "MPX ENERGIA"


def test_fca_name_registry_is_tied_to_exact_filing_receipt_and_keeps_previous_names(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_name_package(package)
    registry, audit = audit_fca_issuer_name_registry(package, 2022)

    assert audit.unique_issuers == 2
    assert audit.missing_available_from == 0
    assert "MPX ENERGIA" in set(registry["company_name_normalized"])
    assert "ALL AMERICA LATINA LOGISTICA" in set(registry["company_name_normalized"])
    mpx = registry.loc[registry["company_name_normalized"].eq("MPX ENERGIA")].iloc[0]
    assert mpx["issuer_id"] == "30.306.294/0001-45"
    assert mpx["available_from"] == pd.Timestamp("2022-03-15", tz="UTC")


def test_unique_short_name_resolution_handles_cotahist_abbreviations(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_name_package(package)
    registry, _ = audit_fca_issuer_name_registry(package, 2022)
    mapping = resolve_fca_name_identity(
        pd.Series(["MPX ENERGIA", "ALL AMER LAT"]), registry
    ).set_index("issuer_short_name")

    assert mapping.loc["MPX ENERGIA", "fca_name_mapping_status"] == "resolved"
    assert mapping.loc["MPX ENERGIA", "fca_name_issuer_id"] == "30.306.294/0001-45"
    assert mapping.loc["ALL AMER LAT", "fca_name_mapping_status"] == "resolved"
    assert mapping.loc["ALL AMER LAT", "fca_name_issuer_id"] == "02.421.421/0001-11"


def test_name_resolution_fails_closed_when_alias_matches_multiple_issuers():
    registry = pd.DataFrame(
        {
            "issuer_id": ["33.000.167/0001-01", "33.592.510/0001-54"],
            "company_name": ["ALFA ENERGIA S.A.", "ALFA ENERGIA DO BRASIL S.A."],
            "company_name_normalized": ["ALFA ENERGIA", "ALFA ENERGIA BRASIL"],
            "reference_date": [pd.Timestamp("2025-01-01")] * 2,
            "available_from": [pd.Timestamp("2025-03-01", tz="UTC")] * 2,
        }
    )
    mapping = resolve_fca_name_identity(pd.Series(["ALFA ENERGIA"]), registry).iloc[0]
    assert mapping["fca_name_mapping_status"] == "ambiguous_name_evidence"
    assert pd.isna(mapping["fca_name_issuer_id"])


def test_name_enrichment_only_fills_unresolved_and_never_overwrites_stronger_identity(tmp_path: Path):
    package = tmp_path / "fca.zip"
    _write_fca_name_package(package)
    registry, _ = audit_fca_issuer_name_registry(package, 2022)
    universe = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2011-01-03"), pd.Timestamp("2011-01-03")],
            "security_id": ["ISIN:BRMPXEACNOR2", "ISIN:BRALLLACNOR6"],
            "ticker": ["MPXE3", "ALLL3"],
            "issuer_short_name": ["MPX ENERGIA", "ALL AMER LAT"],
            "issuer_id": [pd.NA, "33.000.167/0001-01"],
            "identity_mapping_status": ["unresolved_no_fca_evidence", "resolved"],
            "identity_evidence_available_from": [pd.NaT, pd.Timestamp("2019-01-01", tz="UTC")],
            "financial_volume": [100.0, 200.0],
        }
    )

    enriched, audit = enrich_historical_identity_with_fca_names(universe, registry)
    assert enriched.loc[0, "issuer_id"] == "30.306.294/0001-45"
    assert enriched.loc[0, "identity_resolution_method"] == "CVM_FCA_ISSUER_NAME_UNIQUE"
    assert bool(enriched.loc[0, "identity_reconstruction_uses_later_evidence"])
    # Existing stronger identity is preserved even when weak name evidence disagrees.
    assert enriched.loc[1, "issuer_id"] == "33.000.167/0001-01"
    assert bool(enriched.loc[1, "identity_weaker_source_disagreed"])
    assert audit.newly_resolved_rows == 1
    assert audit.disagreement_rows == 1

from __future__ import annotations

import pandas as pd

from mercado_financeiro.pit import (
    enrich_historical_identity_with_verified_evidence,
    verified_historical_identity_evidence,
)


def _universe(*, security_id: str = "ISIN:BRALLLACNOR6", issuer_id: object = pd.NA, status: str = "unresolved_no_name_evidence") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2011-01-03")],
            "security_id": [security_id],
            "ticker": ["ALLL3"],
            "issuer_short_name": ["ALL AMER LAT"],
            "issuer_id": [issuer_id],
            "identity_mapping_status": [status],
            "identity_evidence_available_from": [pd.NaT],
            "financial_volume": [100.0],
        }
    )


def test_verified_registry_is_exact_primary_source_evidence():
    evidence = verified_historical_identity_evidence()
    row = evidence.loc[evidence["security_id"].eq("ISIN:BRALLLACNOR6")].iloc[0]
    assert row["ticker"] == "ALLL3"
    assert row["issuer_short_name"] == "ALL AMER LAT"
    assert row["issuer_id"] == "02.387.241/0001-60"
    assert row["cvm_code"] == "17450"
    assert str(row["ticker_evidence_url"]).startswith("https://sistemas.cvm.gov.br/")
    assert str(row["issuer_evidence_url"]).startswith("https://sistemas.cvm.gov.br/")


def test_verified_evidence_resolves_only_exact_security_tuple_and_preserves_provenance():
    enriched, audit = enrich_historical_identity_with_verified_evidence(_universe())
    row = enriched.iloc[0]
    assert row["issuer_id"] == "02.387.241/0001-60"
    assert row["identity_mapping_status"] == "resolved"
    assert row["identity_resolution_method"] == "CVM_PRIMARY_SOURCE_VERIFIED_SECURITY"
    assert row["identity_evidence_source"] == "CVM_PRIMARY_DOCUMENT_PAIR"
    assert row["identity_evidence_cvm_code"] == "17450"
    assert bool(row["identity_reconstruction_uses_later_evidence"])
    assert audit.newly_resolved_rows == 1
    assert audit.mapped_row_ratio == 1.0
    assert audit.mapped_volume_ratio == 1.0


def test_verified_evidence_does_not_match_same_ticker_with_different_security():
    enriched, audit = enrich_historical_identity_with_verified_evidence(
        _universe(security_id="ISIN:BRNOTAREAL00")
    )
    assert enriched.loc[0, "identity_mapping_status"].startswith("unresolved")
    assert pd.isna(enriched.loc[0, "issuer_id"])
    assert audit.newly_resolved_rows == 0


def test_verified_evidence_never_overwrites_stronger_conflicting_identity():
    enriched, audit = enrich_historical_identity_with_verified_evidence(
        _universe(issuer_id="33.000.167/0001-01", status="resolved")
    )
    assert enriched.loc[0, "issuer_id"] == "33.000.167/0001-01"
    assert bool(enriched.loc[0, "identity_weaker_source_disagreed"])
    assert audit.newly_resolved_rows == 0
    assert audit.disagreement_rows == 1

from __future__ import annotations

import pandas as pd

from mercado_financeiro.pit import (
    combine_b3_isin_registries,
    enrich_historical_identity_with_registry_history,
)


def _registry(security: str, issuer: str, available: str, source: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": [security],
            "issuer_id": [issuer],
            "identity_evidence_available_from": [pd.Timestamp(available)],
            "identity_evidence_source": [source],
            "registry_mapping_status": ["resolved"],
        }
    )


def test_old_security_survives_when_missing_from_current_snapshot():
    old = _registry("BROLDACNOR1", "11.111.111/0001-11", "2022-01-24T00:00:00Z", "ARCHIVE")
    current = _registry("BRNEWACNOR2", "22.222.222/0001-22", "2026-09-15T00:00:00Z", "CURRENT")
    combined = combine_b3_isin_registries([old, current])
    assert set(combined["security_id"]) == {"BROLDACNOR1", "BRNEWACNOR2"}


def test_cross_vintage_isin_disagreement_fails_closed():
    a = _registry("BRTESTACNOR0", "11.111.111/0001-11", "2022-01-24T00:00:00Z", "ARCHIVE")
    b = _registry("BRTESTACNOR0", "22.222.222/0001-22", "2026-09-15T00:00:00Z", "CURRENT")
    combined = combine_b3_isin_registries([a, b])
    assert set(combined["registry_mapping_status"]) == {"ambiguous_registry"}


def test_enrichment_preserves_archived_snapshot_provenance():
    registry = _registry("BRTESTACNOR0", "11.111.111/0001-11", "2022-01-24T00:00:00Z", "B3_ARCHIVE")
    universe = pd.DataFrame(
        {
            "security_id": ["BRTESTACNOR0"],
            "issuer_id": [pd.NA],
            "identity_mapping_status": ["unresolved_no_fca_evidence"],
            "trade_date": [pd.Timestamp("2011-01-03")],
            "financial_volume": [100.0],
            "ticker": ["TEST3"],
        }
    )
    out, audit = enrich_historical_identity_with_registry_history(universe, registry)
    assert audit.newly_resolved_rows == 1
    assert out.loc[0, "issuer_id"] == "11.111.111/0001-11"
    assert out.loc[0, "identity_evidence_source"] == "B3_ARCHIVE"

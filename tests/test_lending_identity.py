import pandas as pd
import pytest

from mercado_financeiro.pit import resolve_lending_identity_asof


def _master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "PETR4",
                "security_id": "ISIN:BRPETRACNPR6",
                "isin": "BRPETRACNPR6",
                "valid_from": "2026-01-01",
                "valid_to_exclusive": None,
            },
            {
                "ticker": "BOVA11",
                "security_id": "ISIN:BRBOVACTF003",
                "isin": "BRBOVACTF003",
                "valid_from": "2026-01-01",
                "valid_to_exclusive": None,
            },
        ]
    )


def test_lending_identity_verifies_source_isin_and_resolves_missing_isin_asof():
    lending = pd.DataFrame(
        [
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "PETR4",
                "security_id": "ISIN:BRPETRACNPR6",
                "isin": "BRPETRACNPR6",
            },
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "BOVA11",
                "security_id": None,
                "isin": None,
            },
        ]
    )

    resolved, audit = resolve_lending_identity_asof(
        lending,
        _master(),
        require_complete=True,
    )

    petr = resolved.loc[resolved["ticker"].eq("PETR4")].iloc[0]
    bova = resolved.loc[resolved["ticker"].eq("BOVA11")].iloc[0]
    assert petr["identity_status"] == "exact_isin_master_verified"
    assert bova["identity_status"] == "security_master_asof"
    assert bova["security_id"] == "ISIN:BRBOVACTF003"
    assert bova["isin"] == "BRBOVACTF003"
    assert audit.source_exact_isin_rows == 1
    assert audit.master_verified_rows == 1
    assert audit.master_resolved_rows == 1
    assert audit.unresolved_rows == 0


def test_lending_identity_fails_on_source_master_conflict():
    lending = pd.DataFrame(
        [
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "PETR4",
                "security_id": "ISIN:BRWRONG00000",
                "isin": "BRWRONG00000",
            }
        ]
    )
    with pytest.raises(ValueError, match="conflicts with active security master"):
        resolve_lending_identity_asof(lending, _master())


def test_lending_identity_fails_on_ambiguous_active_ticker_mapping():
    master = pd.concat(
        [
            _master(),
            pd.DataFrame(
                [
                    {
                        "ticker": "BOVA11",
                        "security_id": "ISIN:BROTHER00001",
                        "isin": "BROTHER00001",
                        "valid_from": "2026-01-01",
                        "valid_to_exclusive": None,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    lending = pd.DataFrame(
        [
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "BOVA11",
                "security_id": None,
                "isin": None,
            }
        ]
    )
    with pytest.raises(ValueError, match="ambiguous active ticker-to-security mapping"):
        resolve_lending_identity_asof(lending, master)


def test_lending_identity_can_audit_but_not_promote_unresolved_ticker():
    lending = pd.DataFrame(
        [
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "UNKNOWN1",
                "security_id": None,
                "isin": None,
            }
        ]
    )
    unresolved, audit = resolve_lending_identity_asof(lending, _master())
    assert unresolved.loc[0, "identity_status"] == "unresolved_ticker"
    assert pd.isna(unresolved.loc[0, "security_id"])
    assert audit.unresolved_rows == 1

    with pytest.raises(ValueError, match="unresolved B3 lending identities remain"):
        resolve_lending_identity_asof(lending, _master(), require_complete=True)


def test_lending_identity_respects_historical_validity_interval():
    master = _master()
    master.loc[master["ticker"].eq("BOVA11"), "valid_to_exclusive"] = "2026-07-01"
    lending = pd.DataFrame(
        [
            {
                "reference_date": "2026-09-18T00:00:00Z",
                "ticker": "BOVA11",
                "security_id": None,
                "isin": None,
            }
        ]
    )
    resolved, audit = resolve_lending_identity_asof(lending, master)
    assert resolved.loc[0, "identity_status"] == "unresolved_ticker"
    assert audit.unresolved_rows == 1

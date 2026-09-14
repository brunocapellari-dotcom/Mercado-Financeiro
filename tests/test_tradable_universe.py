import pandas as pd

from mercado_financeiro.pit.universe import (
    build_tradable_universe_pit,
    resolve_fca_identity_asof,
)


def _fca_history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "OLD3",
                "issuer_id": "00.000.001/0001-00",
                "share_class": "ordinary",
                "preferred_class": pd.NA,
                "valid_from": "2010-01-01",
                "valid_to_exclusive": pd.NaT,
                "reference_date": "2019-01-01",
                "available_from": "2019-04-10",
            },
            {
                "ticker": "NOW4",
                "issuer_id": "00.000.002/0001-00",
                "share_class": "preferred",
                "preferred_class": pd.NA,
                "valid_from": "2010-01-01",
                "valid_to_exclusive": pd.NaT,
                "reference_date": "2011-01-01",
                "available_from": "2011-03-01",
            },
        ]
    )


def _quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2011-06-01",
                "security_id": "ISIN:BROLD0000001",
                "isin": "BROLD0000001",
                "ticker": "OLD3",
                "close_price": 10.0,
                "financial_volume": 1000.0,
                "trades": 10,
                "quantity": 100,
                "bdi_code": "02",
                "specification": "ON",
            },
            {
                "trade_date": "2011-06-01",
                "security_id": "ISIN:BRNOW0000002",
                "isin": "BRNOW0000002",
                "ticker": "NOW4",
                "close_price": 20.0,
                "financial_volume": 9000.0,
                "trades": 50,
                "quantity": 450,
                "bdi_code": "02",
                "specification": "PN",
            },
        ]
    )


def test_strict_publication_does_not_backfill_future_fca_evidence():
    mapping = resolve_fca_identity_asof(
        _fca_history(), "2011-06-01", policy="strict_publication"
    )
    assert set(mapping["ticker"]) == {"NOW4"}


def test_historical_identity_can_name_observed_old_security_but_keeps_evidence_time():
    mapping = resolve_fca_identity_asof(
        _fca_history(), "2011-06-01", policy="historical_identity"
    )
    assert set(mapping["ticker"]) == {"OLD3", "NOW4"}
    old = mapping.loc[mapping["ticker"] == "OLD3"].iloc[0]
    assert old["issuer_id"] == "00.000.001/0001-00"
    assert old["identity_evidence_available_from"] == pd.Timestamp("2019-04-10")


def test_observed_universe_membership_is_from_cotahist_and_audits_later_identity_evidence():
    universe, audit = build_tradable_universe_pit(
        _quotes(), _fca_history(), identity_policy="historical_identity"
    )
    assert universe["tradable_observed"].all()
    assert set(universe["ticker"]) == {"OLD3", "NOW4"}
    assert audit.mapped_rows == 2
    assert audit.unresolved_rows == 0
    assert audit.later_identity_evidence_rows == 1
    assert audit.mapped_row_ratio == 1.0
    assert audit.mapped_volume_ratio == 1.0


def test_strict_universe_reports_unresolved_rows_without_dropping_observed_security():
    universe, audit = build_tradable_universe_pit(
        _quotes(), _fca_history(), identity_policy="strict_publication"
    )
    assert len(universe) == 2
    old = universe.loc[universe["ticker"] == "OLD3"].iloc[0]
    assert old["identity_mapping_status"] == "unresolved_no_fca_evidence"
    assert audit.mapped_rows == 1
    assert audit.unresolved_rows == 1
    assert audit.mapped_row_ratio == 0.5
    assert audit.mapped_volume_ratio == 0.9


def test_overlapping_different_issuers_are_marked_ambiguous_not_silently_chosen():
    history = pd.concat(
        [
            _fca_history(),
            pd.DataFrame(
                [
                    {
                        "ticker": "OLD3",
                        "issuer_id": "99.999.999/0001-99",
                        "share_class": "ordinary",
                        "preferred_class": pd.NA,
                        "valid_from": "2010-01-01",
                        "valid_to_exclusive": pd.NaT,
                        "reference_date": "2020-01-01",
                        "available_from": "2020-03-01",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    mapping = resolve_fca_identity_asof(history, "2011-06-01", policy="historical_identity")
    old = mapping.loc[mapping["ticker"] == "OLD3"].iloc[0]
    assert pd.isna(old["issuer_id"])
    assert old["identity_mapping_status"] == "ambiguous_issuer"

from datetime import datetime, timezone

import pandas as pd
import pytest

from mercado_financeiro.data import (
    BCBSeries,
    NewsEvent,
    fundamentals_asof,
    get_bcb_series_contract,
    get_source_contract,
    macro_asof,
    news_body_digest,
    validate_fundamental_observations,
    validate_macro_observations,
)


def test_bcb_catalog_uses_verified_core_series_and_no_unaudited_release_lag():
    assert get_bcb_series_contract(BCBSeries.SELIC_TARGET).sgs_code == 432
    assert get_bcb_series_contract(BCBSeries.SELIC_DAILY).sgs_code == 11
    assert get_bcb_series_contract(BCBSeries.IPCA_MONTHLY).sgs_code == 433
    assert get_bcb_series_contract(BCBSeries.USD_BRL_SELL).sgs_code == 1
    assert get_bcb_series_contract(BCBSeries.USD_BRL_BUY).sgs_code == 10813
    assert all(
        get_bcb_series_contract(item).publication_lag_days is None
        for item in BCBSeries
    )


def test_source_registry_marks_official_and_credentialed_sources():
    assert get_source_contract("BCB").canonical
    assert get_source_contract("CVM").canonical
    assert get_source_contract("ANBIMA").credentials_required
    brapi = get_source_contract("BRAPI")
    assert not brapi.canonical
    assert not brapi.live_capable
    assert not brapi.credentials_required
    assert not get_source_contract("DATABENTO").canonical
    with pytest.raises(KeyError):
        get_source_contract("unknown")


def test_fundamental_vintage_selector_never_uses_later_refiling_early():
    frame = pd.DataFrame(
        {
            "issuer_id": ["A", "A"],
            "metric": ["equity", "equity"],
            "value": [100.0, 120.0],
            "reference_date": ["2025-12-31", "2025-12-31"],
            "available_from": ["2026-03-01T12:00:00Z", "2026-05-01T12:00:00Z"],
            "filing_version": [1, 2],
            "source": ["CVM_DFP", "CVM_DFP"],
        }
    )
    validated, audit = validate_fundamental_observations(frame)
    assert audit.rows == 2
    march = fundamentals_asof(validated, "2026-03-31T23:59:59Z")
    june = fundamentals_asof(validated, "2026-06-01T00:00:00Z")
    assert march.iloc[0]["value"] == 100.0
    assert june.iloc[0]["value"] == 120.0


def test_macro_vintage_selector_keeps_latest_known_revision_only_after_availability():
    frame = pd.DataFrame(
        {
            "series_id": ["IPCA", "IPCA"],
            "reference_date": ["2026-01-31", "2026-01-31"],
            "available_from": ["2026-02-10T12:00:00Z", "2026-03-01T12:00:00Z"],
            "value": [0.5, 0.6],
            "source": ["BCB", "BCB"],
            "vintage_id": ["v1", "v2"],
        }
    )
    validated, audit = validate_macro_observations(frame)
    assert audit.rows == 2
    feb = macro_asof(validated, "2026-02-15T00:00:00Z")
    mar = macro_asof(validated, "2026-03-15T00:00:00Z")
    assert feb.iloc[0]["value"] == 0.5
    assert mar.iloc[0]["value"] == 0.6


def test_news_availability_is_received_timestamp_not_publisher_clock():
    body = "material fact"
    event = NewsEvent(
        provider="feed",
        article_id="1",
        published_at=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 9, 15, 12, 0, 3, tzinfo=timezone.utc),
        headline="Headline",
        source_url="https://example.invalid/article/1",
        body_digest=news_body_digest(body),
    )
    assert event.available_from == event.received_at
    assert len(event.body_digest) == 64

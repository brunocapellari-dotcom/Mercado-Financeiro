from __future__ import annotations

import pandas as pd
import pytest

from mercado_financeiro.pit.security_master import (
    build_security_master_scd2,
    validate_security_master_scd2,
)


def _obs(date: str, ticker: str = "AAAA3", instrument_id: str = "1") -> dict[str, object]:
    return {
        "listing_id": "ISIN:BRAAAAACNOR0:MKT=10:SGMT=1",
        "security_id": "ISIN:BRAAAAACNOR0",
        "observation_date": date,
        "ticker": ticker,
        "instrument_id": instrument_id,
        "isin": "BRAAAAACNOR0",
        "market": "10",
        "segment": "1",
        "security_category": "11",
        "cfi_code": "ESVUFR",
        "specification_code": "ON NM",
        "corporation_name": "AAAA S.A.",
        "trading_start_date": "2020-01-01",
        "trading_end_date": "9999-12-31",
    }


def test_scd2_keeps_unchanged_state_open():
    history = build_security_master_scd2(pd.DataFrame([_obs("2026-08-20"), _obs("2026-08-21")]))
    assert len(history) == 1
    assert history.loc[0, "snapshot_count"] == 2
    assert pd.isna(history.loc[0, "valid_to_exclusive"])
    assert history.loc[0, "valid_from"] == pd.Timestamp("2026-08-20")


def test_scd2_closes_and_reopens_on_ticker_or_instrument_change():
    history = build_security_master_scd2(
        pd.DataFrame(
            [
                _obs("2026-08-20", ticker="AAAA3", instrument_id="1"),
                _obs("2026-08-21", ticker="AAAB3", instrument_id="2"),
            ]
        )
    )
    assert len(history) == 2
    assert history.loc[0, "valid_to_exclusive"] == pd.Timestamp("2026-08-21")
    assert history.loc[1, "ticker"] == "AAAB3"
    assert pd.isna(history.loc[1, "valid_to_exclusive"])


def test_scd2_absence_closes_at_first_confirmed_missing_snapshot():
    second = _obs("2026-08-21")
    second["listing_id"] = "ISIN:BRBBBBACNOR0:MKT=10:SGMT=1"
    second["security_id"] = "ISIN:BRBBBBACNOR0"
    second["isin"] = "BRBBBBACNOR0"
    second["ticker"] = "BBBB3"
    history = build_security_master_scd2(pd.DataFrame([_obs("2026-08-20"), second]))
    aaaa = history.loc[history["security_id"] == "ISIN:BRAAAAACNOR0"].iloc[0]
    assert aaaa["valid_to_exclusive"] == pd.Timestamp("2026-08-21")
    assert aaaa["last_observed_date"] == pd.Timestamp("2026-08-20")


def test_scd2_rejects_duplicate_listing_in_same_snapshot():
    df = pd.DataFrame([_obs("2026-08-20"), _obs("2026-08-20")])
    with pytest.raises(ValueError, match="duplicate listing_id"):
        build_security_master_scd2(df)


def test_validator_rejects_overlapping_intervals():
    bad = pd.DataFrame(
        {
            "listing_id": ["A", "A"],
            "valid_from": ["2026-01-01", "2026-01-05"],
            "valid_to_exclusive": ["2026-01-10", None],
        }
    )
    with pytest.raises(ValueError, match="overlapping"):
        validate_security_master_scd2(bad)

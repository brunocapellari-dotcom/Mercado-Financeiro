import pandas as pd
import pytest

from mercado_financeiro.pit.corporate_actions import (
    compute_total_returns,
    normalize_corporate_actions,
)


def _prices(values):
    return pd.DataFrame(
        {
            "security_id": ["TEST3"] * len(values),
            "price_date": pd.to_datetime(["2026-01-01", "2026-01-02"][: len(values)]),
            "close_price": values,
        }
    )


def test_cash_dividend_total_return_uses_unadjusted_price_plus_cash():
    events = pd.DataFrame(
        {
            "security_id": ["TEST3"],
            "effective_date": ["2026-01-02"],
            "action_type": ["cash_dividend"],
            "available_from": ["2025-12-20T12:00:00Z"],
            "cash_per_share": [5.0],
        }
    )
    result, audit = compute_total_returns(_prices([100.0, 95.0]), events)
    assert result.loc[1, "raw_price_return"] == pytest.approx(-0.05)
    assert result.loc[1, "total_return"] == pytest.approx(0.0)
    assert audit.cash_event_days == 1


def test_split_total_return_neutralizes_mechanical_price_change():
    events = pd.DataFrame(
        {
            "security_id": ["TEST3"],
            "effective_date": ["2026-01-02"],
            "action_type": ["split"],
            "available_from": ["2025-12-20T12:00:00Z"],
            "share_ratio": [2.0],
        }
    )
    result, audit = compute_total_returns(_prices([100.0, 50.0]), events)
    assert result.loc[1, "raw_price_return"] == pytest.approx(-0.5)
    assert result.loc[1, "total_return"] == pytest.approx(0.0)
    assert audit.share_ratio_event_days == 1


def test_complex_action_fails_closed_in_total_return():
    events = pd.DataFrame(
        {
            "security_id": ["TEST3"],
            "effective_date": ["2026-01-02"],
            "action_type": ["merger"],
            "available_from": ["2025-12-20T12:00:00Z"],
        }
    )
    result, audit = compute_total_returns(_prices([100.0, 110.0]), events)
    assert pd.isna(result.loc[1, "total_return"])
    assert result.loc[1, "total_return_status"] == "blocked_complex_corporate_action"
    assert audit.blocked_complex_event_days == 1


def test_invalid_split_ratio_is_rejected():
    events = pd.DataFrame(
        {
            "security_id": ["TEST3"],
            "effective_date": ["2026-01-02"],
            "action_type": ["split"],
            "available_from": ["2025-12-20T12:00:00Z"],
            "share_ratio": [1.0],
        }
    )
    with pytest.raises(ValueError, match="different from 1"):
        normalize_corporate_actions(events)

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings, strategies as st
import pandas as pd

from mercado_financeiro.pit import available_asof
from mercado_financeiro.research import point_in_time_asof_join


@settings(max_examples=50, deadline=None)
@given(
    publication_lag=st.integers(min_value=0, max_value=365),
    observation_lag=st.integers(min_value=0, max_value=500),
)
def test_point_in_time_fundamental_join_never_exposes_future_publication(
    publication_lag: int,
    observation_lag: int,
):
    reference = date(2025, 1, 1)
    available = reference + timedelta(days=publication_lag)
    observation = reference + timedelta(days=observation_lag)
    observations = pd.DataFrame(
        {"issuer_id": ["A"], "feature_date": [pd.Timestamp(observation)]}
    )
    fundamentals = pd.DataFrame(
        {
            "issuer_id": ["A"],
            "reference_date": [pd.Timestamp(reference)],
            "available_from": [pd.Timestamp(available)],
            "value": [123.0],
        }
    )

    result = point_in_time_asof_join(observations, fundamentals).iloc[0]
    if observation >= available:
        assert result["value"] == 123.0
        assert pd.Timestamp(result["available_from"]) <= pd.Timestamp(observation)
    else:
        assert pd.isna(result["value"])


@settings(max_examples=50, deadline=None)
@given(
    cutoff_lag=st.integers(min_value=0, max_value=500),
    first_lag=st.integers(min_value=0, max_value=250),
    second_lag=st.integers(min_value=251, max_value=500),
)
def test_available_asof_is_monotone_and_contains_no_future_rows(
    cutoff_lag: int,
    first_lag: int,
    second_lag: int,
):
    origin = pd.Timestamp("2025-01-01")
    frame = pd.DataFrame(
        {
            "available_from": [
                origin + pd.Timedelta(days=first_lag),
                origin + pd.Timedelta(days=second_lag),
            ],
            "value": [1, 2],
        }
    )
    cutoff = origin + pd.Timedelta(days=cutoff_lag)
    result = available_asof(frame, cutoff)
    assert (pd.to_datetime(result["available_from"]) <= cutoff).all()

    later = available_asof(frame, cutoff + pd.Timedelta(days=30))
    assert len(later) >= len(result)

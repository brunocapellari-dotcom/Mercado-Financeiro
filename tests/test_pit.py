from __future__ import annotations

import pandas as pd
import pytest

from mercado_financeiro.pit.cvm import available_asof
from mercado_financeiro.pit.survivorship import coverage_audit


def test_available_asof_blocks_future_version():
    df = pd.DataFrame({
        "value": [1, 2],
        "available_from": pd.to_datetime(["2020-03-31", "2020-05-15"]),
    })
    out = available_asof(df, "2020-04-01")
    assert out["value"].tolist() == [1]


def test_available_asof_requires_non_null_availability():
    df = pd.DataFrame({"available_from": [None]})
    with pytest.raises(ValueError):
        available_asof(df, "2020-01-01")


def test_survivorship_audit_estimates_unmapped_and_gates():
    df = pd.DataFrame({
        "year": [2011, 2026],
        "observations": [1000, 1000],
        "mapped_obs_share": [0.827, 0.998],
        "mapped_volume_share": [0.938, 0.99999],
    })
    out = coverage_audit(df)
    assert out["unmapped_observations_est"].tolist() == [173, 2]
    assert out["obs_gate_99pct"].tolist() == [False, True]
    assert out["volume_gate_99pct"].tolist() == [False, True]

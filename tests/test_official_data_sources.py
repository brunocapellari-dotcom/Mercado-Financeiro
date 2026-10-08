from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from mercado_financeiro.data import (
    AnbimaFeedSource,
    BCBSgsSource,
    NEFINRiskFactorsSource,
    VintageMode,
    asof,
)
from mercado_financeiro.security import SourceSecurityError, validate_source_url


def test_bcb_defaults_to_conservative_retrieval(monkeypatch):
    payload = json.dumps(
        [{"data": "01/09/2026", "valor": "14.90"}, {"data": "02/09/2026", "valor": "14,91"}]
    ).encode()
    monkeypatch.setattr(\n        "mercado_financeiro.data.bcb.download_https_with_retry",\n        lambda url, policy, **kwargs: payload,\n    )
    retrieved = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    dataset = BCBSgsSource().fetch(1178, retrieved_at=retrieved)
    assert dataset.vintage_mode == VintageMode.CONSERVATIVE_RETRIEVAL
    assert dataset.frame["available_from"].eq(pd.Timestamp(retrieved)).all()
    assert asof(dataset.frame, "2026-09-14T23:59:59Z").empty
    assert len(asof(dataset.frame, "2026-09-15T12:00:00Z")) == 2


def test_bcb_future_effective_value_can_be_known_before_reference_date(monkeypatch):
    payload = b'[{"data":"16/09/2026","valor":"14.75"}]'
    monkeypatch.setattr(\n        "mercado_financeiro.data.bcb.download_https_with_retry",\n        lambda url, policy, **kwargs: payload,\n    )
    retrieved = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
    dataset = BCBSgsSource().fetch(432, retrieved_at=retrieved)
    row = dataset.frame.iloc[0]
    assert row["reference_date"] == pd.Timestamp("2026-09-16", tz="UTC")
    assert row["available_from"] == pd.Timestamp(retrieved)
    # PIT means "what was known", not "effective date <= cutoff".
    assert len(asof(dataset.frame, retrieved)) == 1


def test_bcb_publication_lag_must_be_explicit(monkeypatch):
    payload = b'[{"data":"01/09/2026","valor":"1.0"}]'
    monkeypatch.setattr(\n        "mercado_financeiro.data.bcb.download_https_with_retry",\n        lambda url, policy, **kwargs: payload,\n    )
    dataset = BCBSgsSource().fetch(1, publication_lag_days=1)
    assert dataset.vintage_mode == VintageMode.PUBLICATION_GATED
    assert dataset.frame.loc[0, "available_from"] == pd.Timestamp("2026-09-02", tz="UTC")


def test_nefin_is_benchmark_only_and_not_backfilled(monkeypatch):
    payload = b"date,rm_minus_rf,smb\n2026-07-02,0.01,0.02\n2026-07-03,-0.01,0.00\n"
    monkeypatch.setattr("mercado_financeiro.data.nefin.download_https", lambda url, policy: payload)
    retrieved = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    dataset = NEFINRiskFactorsSource().fetch(retrieved_at=retrieved)
    assert dataset.vintage_mode == VintageMode.BENCHMARK_ONLY
    assert list(dataset.frame["reference_date"]) == [
        pd.Timestamp("2026-07-02", tz="UTC"),
        pd.Timestamp("2026-07-03", tz="UTC"),
    ]
    assert dataset.frame["available_from"].eq(pd.Timestamp(retrieved)).all()


def test_anbima_token_is_not_persisted_in_source(monkeypatch):
    response = json.dumps({"access_token": "temporary-token", "expires_in": 3600}).encode()

    def fake_request(url, policy, **kwargs):
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["Authorization"].startswith("Basic ")
        assert b"client_secret" not in kwargs["body"]
        return response

    monkeypatch.setattr("mercado_financeiro.data.anbima.request_https", fake_request)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    source = AnbimaFeedSource(sandbox=True)
    token = source.obtain_access_token(client_id="client", client_secret="secret", now=now)
    assert token.token == "temporary-token"
    assert not hasattr(source, "client_secret")
    assert not hasattr(source, "access_token")


def test_official_macro_hosts_are_allowlisted_and_spoofed_hosts_are_not():
    assert validate_source_url("https://api.bcb.gov.br/x")
    assert validate_source_url("https://api.anbima.com.br/x")
    assert validate_source_url("https://nefin.com.br/x")
    with pytest.raises(SourceSecurityError):
        validate_source_url("https://api.bcb.gov.br.evil.example/x")

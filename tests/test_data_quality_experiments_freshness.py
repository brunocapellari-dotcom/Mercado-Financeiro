from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from mercado_financeiro.data import DataQualityContract, assert_data_quality, evaluate_data_quality
from mercado_financeiro.research import (
    ExperimentRecorder,
    ExperimentRunManifest,
    ExperimentStatus,
    assert_feature_freshness,
)


def test_data_quality_contract_checks_uniqueness_range_and_freshness():
    frame = pd.DataFrame(
        {
            "security_id": ["A", "B"],
            "timestamp": pd.to_datetime(["2026-09-15T12:00:00Z", "2026-09-15T12:01:00Z"]),
            "price": [10.0, 20.0],
        }
    )
    contract = DataQualityContract(
        name="prices",
        required_columns=("security_id", "timestamp", "price"),
        not_null_columns=("security_id", "price"),
        unique_key=("security_id", "timestamp"),
        timestamp_column="timestamp",
        max_age=timedelta(minutes=5),
    )
    result = assert_data_quality(
        frame,
        contract,
        as_of=pd.Timestamp("2026-09-15T12:03:00Z"),
        numeric_ranges={"price": (0.0, None)},
    )
    assert result.passed

    stale = evaluate_data_quality(
        frame,
        contract,
        as_of=pd.Timestamp("2026-09-15T13:03:00Z"),
    )
    assert not stale.passed
    assert any("stale_latest" in violation for violation in stale.violations)


def test_experiment_manifest_is_immutable_and_integrity_checked():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    manifest = ExperimentRunManifest.build(
        run_id="run-001",
        experiment_name="walk-forward",
        code_commit_sha="abcdef1",
        dataset_manifest_sha256="a" * 64,
        feature_manifest_sha256="b" * 64,
        started_at=now,
        ended_at=now + timedelta(minutes=1),
        status=ExperimentStatus.SUCCEEDED,
        parameters={"lookback": 63, "long_only": True},
        metrics={"sharpe": 1.25},
        artifact_sha256=("c" * 64,),
    )
    recorder = ExperimentRecorder()
    digest = recorder.record(manifest)
    assert len(digest) == 64
    assert recorder.get("run-001") == manifest
    with pytest.raises(ValueError, match="already exists"):
        recorder.record(manifest)


def test_feature_freshness_blocks_stale_and_future_sources():
    frame = pd.DataFrame(
        {
            "event_at": pd.to_datetime(["2026-09-15T12:00:00Z"]),
            "source_at": pd.to_datetime(["2026-09-15T11:55:00Z"]),
        }
    )
    assert_feature_freshness(
        frame,
        event_timestamp_column="event_at",
        source_timestamp_column="source_at",
        max_age=timedelta(minutes=10),
    )
    with pytest.raises(RuntimeError, match="stale"):
        assert_feature_freshness(
            frame,
            event_timestamp_column="event_at",
            source_timestamp_column="source_at",
            max_age=timedelta(minutes=1),
        )
    future = frame.copy()
    future["source_at"] = pd.to_datetime(["2026-09-15T12:00:01Z"])
    with pytest.raises(RuntimeError, match="look-ahead"):
        assert_feature_freshness(
            future,
            event_timestamp_column="event_at",
            source_timestamp_column="source_at",
            max_age=timedelta(minutes=10),
        )

from datetime import datetime, timezone

import pandas as pd
import pytest

from mercado_financeiro.research import (
    FeatureField,
    FeatureSchema,
    assert_feature_cutoff,
    assert_training_serving_parity,
    build_feature_snapshot_manifest,
    validate_feature_frame,
)


def _schema() -> FeatureSchema:
    return FeatureSchema(
        name="daily-b3-baseline",
        version="1",
        entity_keys=("security_id",),
        event_timestamp_column="feature_date",
        fields=(
            FeatureField("momentum_21", "numeric"),
            FeatureField("adv_21", "numeric"),
        ),
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": ["PETR4", "VALE3"],
            "feature_date": pd.to_datetime(["2026-09-14", "2026-09-14"], utc=True),
            "source_max_date": pd.to_datetime(["2026-09-13", "2026-09-13"], utc=True),
            "momentum_21": [0.02, -0.01],
            "adv_21": [1_000_000.0, 2_000_000.0],
        }
    )


def test_schema_hash_snapshot_and_cutoff_are_deterministic():
    frame = _frame()
    schema = _schema()
    validate_feature_frame(frame, schema)
    assert_feature_cutoff(
        frame,
        event_timestamp_column="feature_date",
        source_max_timestamp_column="source_max_date",
    )
    manifest = build_feature_snapshot_manifest(
        frame,
        schema,
        as_of_cutoff=datetime(2026, 9, 15, tzinfo=timezone.utc),
        parent_sha256=("a" * 64, "b" * 64),
        code_commit_sha="abcdef1234567",
    )
    reordered = frame.iloc[::-1].reset_index(drop=True)
    manifest2 = build_feature_snapshot_manifest(
        reordered,
        schema,
        as_of_cutoff=datetime(2026, 9, 15, tzinfo=timezone.utc),
        parent_sha256=("a" * 64, "b" * 64),
        code_commit_sha="abcdef1234567",
    )
    assert manifest.schema_sha256 == schema.digest()
    assert manifest.content_sha256 == manifest2.content_sha256
    assert manifest.row_count == 2


def test_feature_lookahead_is_rejected():
    frame = _frame()
    frame.loc[0, "source_max_date"] = frame.loc[0, "feature_date"]
    with pytest.raises(RuntimeError, match="look-ahead"):
        assert_feature_cutoff(
            frame,
            event_timestamp_column="feature_date",
            source_max_timestamp_column="source_max_date",
        )


def test_training_serving_schema_drift_is_rejected():
    training = _frame()
    serving = _frame()
    assert_training_serving_parity(training, serving, _schema())
    serving["adv_21"] = serving["adv_21"].astype("int64")
    with pytest.raises(RuntimeError, match="dtype mismatch"):
        assert_training_serving_parity(training, serving, _schema())

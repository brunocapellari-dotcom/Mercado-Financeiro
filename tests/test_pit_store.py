from __future__ import annotations

from hashlib import sha256

import pandas as pd
import pytest

from mercado_financeiro.data import (
    PITSnapshotStore,
    SchemaDriftError,
    SnapshotConflictError,
)


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def test_duckdb_pit_store_filters_future_information_before_latest_selection():
    old = pd.DataFrame(
        {
            "issuer_id": ["A", "B"],
            "reference_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
            "available_from": pd.to_datetime(["2026-03-01", "2026-03-01"], utc=True),
            "book_value": [100.0, 200.0],
        }
    )
    revised = pd.DataFrame(
        {
            "issuer_id": ["A", "B"],
            "reference_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
            "available_from": pd.to_datetime(["2026-05-01", "2026-05-01"], utc=True),
            "book_value": [125.0, 220.0],
        }
    )

    with PITSnapshotStore() as store:
        first = store.ingest_snapshot(
            "fundamentals",
            old,
            snapshot_id="2026-03-01",
            source_sha256=_digest(b"old"),
            retrieved_at="2026-03-02T12:00:00Z",
        )
        second = store.ingest_snapshot(
            "fundamentals",
            revised,
            snapshot_id="2026-05-01",
            source_sha256=_digest(b"revised"),
            retrieved_at="2026-05-02T12:00:00Z",
        )
        assert not first.idempotent
        assert not second.idempotent

        march = store.latest_asof(
            "fundamentals",
            "2026-03-31T23:59:59Z",
            partition_by=["issuer_id", "reference_date"],
        ).set_index("issuer_id")
        assert march.loc["A", "book_value"] == 100.0
        assert march.loc["B", "book_value"] == 200.0
        assert pd.to_datetime(march["available_from"], utc=True).max() <= pd.Timestamp(
            "2026-03-31T23:59:59Z"
        )

        may = store.latest_asof(
            "fundamentals",
            "2026-05-31T23:59:59Z",
            partition_by=["issuer_id", "reference_date"],
        ).set_index("issuer_id")
        assert may.loc["A", "book_value"] == 125.0
        assert may.loc["B", "book_value"] == 220.0


def test_snapshot_id_is_idempotent_only_for_identical_content_contract():
    frame = pd.DataFrame(
        {
            "issuer_id": ["A"],
            "available_from": pd.to_datetime(["2026-01-01"], utc=True),
            "value": [1.0],
        }
    )
    digest = _digest(b"snapshot")
    with PITSnapshotStore() as store:
        store.ingest_snapshot(
            "macro",
            frame,
            snapshot_id="one",
            source_sha256=digest,
            retrieved_at="2026-01-02T00:00:00Z",
        )
        receipt = store.ingest_snapshot(
            "macro",
            frame,
            snapshot_id="one",
            source_sha256=digest,
            retrieved_at="2026-01-03T00:00:00Z",
        )
        assert receipt.idempotent
        assert len(store.snapshots("macro")) == 1

        with pytest.raises(SnapshotConflictError):
            store.ingest_snapshot(
                "macro",
                frame.assign(value=2.0),
                snapshot_id="one",
                source_sha256=_digest(b"different"),
                retrieved_at="2026-01-03T00:00:00Z",
            )


def test_schema_drift_is_rejected_instead_of_silently_mutating_dataset():
    first = pd.DataFrame(
        {
            "issuer_id": ["A"],
            "available_from": pd.to_datetime(["2026-01-01"], utc=True),
            "value": [1.0],
        }
    )
    changed = first.assign(extra=["unexpected"])
    with PITSnapshotStore() as store:
        store.ingest_snapshot(
            "fundamentals",
            first,
            snapshot_id="a",
            source_sha256=_digest(b"a"),
            retrieved_at="2026-01-02T00:00:00Z",
        )
        with pytest.raises(SchemaDriftError):
            store.ingest_snapshot(
                "fundamentals",
                changed,
                snapshot_id="b",
                source_sha256=_digest(b"b"),
                retrieved_at="2026-01-03T00:00:00Z",
            )


def test_store_rejects_unsafe_identifiers_and_naive_cutoffs():
    frame = pd.DataFrame(
        {
            "issuer_id": ["A"],
            "available_from": pd.to_datetime(["2026-01-01"], utc=True),
            "value": [1.0],
        }
    )
    with PITSnapshotStore() as store:
        with pytest.raises(ValueError):
            store.ingest_snapshot(
                "bad;drop",
                frame,
                snapshot_id="a",
                source_sha256=_digest(b"a"),
                retrieved_at="2026-01-02T00:00:00Z",
            )
        store.ingest_snapshot(
            "safe",
            frame,
            snapshot_id="a",
            source_sha256=_digest(b"a"),
            retrieved_at="2026-01-02T00:00:00Z",
        )
        with pytest.raises(ValueError):
            store.latest_asof(
                "safe",
                "2026-01-03",
                partition_by=["issuer_id"],
            )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Iterable

import duckdb
import pandas as pd

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_RESERVED_COLUMNS = frozenset({"__snapshot_id", "__source_sha256", "__retrieved_at"})


class SnapshotConflictError(RuntimeError):
    """Raised when an immutable snapshot id is reused with different content."""


class SchemaDriftError(RuntimeError):
    """Raised when an append would silently change a canonical dataset schema."""


@dataclass(frozen=True)
class SnapshotReceipt:
    dataset: str
    snapshot_id: str
    source_sha256: str
    schema_fingerprint: str
    rows: int
    idempotent: bool


def _identifier(value: str, *, kind: str) -> str:
    text = str(value).strip()
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"invalid {kind} identifier: {value!r}")
    return text


def _quoted(identifier: str) -> str:
    """Return a quoted SQL identifier after enforcing the local identifier grammar."""

    safe = _identifier(identifier, kind="SQL")
    return '"' + safe + '"'


def _sql(*parts: str) -> str:
    """Central SQL assembly boundary for validated identifiers plus static SQL.

    Runtime values never enter through this helper; they are passed separately as
    DuckDB parameters. Dynamic identifiers must already have passed ``_quoted``.
    Keeping SQL assembly in one boundary makes the injection surface auditable and
    avoids scattered string interpolation throughout the store.
    """

    return "".join(parts)


def _digest(value: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    return text


def _utc_timestamp(value: datetime | pd.Timestamp | str, *, field: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return ts.tz_convert("UTC")


def _schema_fingerprint(frame: pd.DataFrame) -> str:
    payload = [(str(column), str(dtype)) for column, dtype in frame.dtypes.items()]
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(encoded).hexdigest()


class PITSnapshotStore:
    """Immutable point-in-time analytical store backed by DuckDB.

    DuckDB is used as the local analytical execution engine, not as a replacement
    for canonical B3/CVM raw files. Every append carries a source hash, retrieval
    timestamp and immutable snapshot id. Point-in-time queries filter by
    ``available_from`` before any latest-row selection, so future information cannot
    enter a historical view.

    Dataset and column identifiers are restricted to a conservative grammar; raw SQL
    supplied by callers is intentionally not accepted by this boundary.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = duckdb.connect(str(database))
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS __mf_pit_snapshots (
                dataset VARCHAR NOT NULL,
                snapshot_id VARCHAR NOT NULL,
                source_sha256 VARCHAR NOT NULL,
                retrieved_at TIMESTAMPTZ NOT NULL,
                rows BIGINT NOT NULL,
                schema_fingerprint VARCHAR NOT NULL,
                PRIMARY KEY (dataset, snapshot_id)
            )
            """
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PITSnapshotStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _table_name(dataset: str) -> str:
        return "pit__" + _identifier(dataset, kind="dataset").lower()

    def _table_exists(self, table: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?",
            [table],
        ).fetchone()
        return row is not None

    def _base_columns(self, table: str) -> list[str]:
        query = _sql("DESCRIBE ", _quoted(table))
        rows = self._connection.execute(query).fetchall()
        return [str(row[0]) for row in rows if str(row[0]) not in _RESERVED_COLUMNS]

    def ingest_snapshot(
        self,
        dataset: str,
        frame: pd.DataFrame,
        *,
        snapshot_id: str,
        source_sha256: str,
        retrieved_at: datetime | pd.Timestamp | str,
        available_from_column: str = "available_from",
    ) -> SnapshotReceipt:
        dataset = _identifier(dataset, kind="dataset")
        table = self._table_name(dataset)
        snapshot_id = str(snapshot_id).strip()
        if not snapshot_id or len(snapshot_id) > 256:
            raise ValueError("snapshot_id must be non-empty and <= 256 characters")
        source_sha256 = _digest(source_sha256)
        retrieved = _utc_timestamp(retrieved_at, field="retrieved_at")
        available_from_column = _identifier(available_from_column, kind="column")

        if frame.empty:
            raise ValueError("snapshot frame must not be empty")
        if frame.columns.duplicated().any():
            raise ValueError("snapshot frame contains duplicate columns")
        columns = [str(column) for column in frame.columns]
        for column in columns:
            _identifier(column, kind="column")
        reserved = _RESERVED_COLUMNS.intersection(columns)
        if reserved:
            raise ValueError(f"snapshot frame uses reserved columns: {sorted(reserved)}")
        if available_from_column not in columns:
            raise ValueError(f"snapshot requires {available_from_column!r}")

        prepared = frame.copy()
        prepared[available_from_column] = pd.to_datetime(
            prepared[available_from_column], errors="coerce", utc=True
        )
        if prepared[available_from_column].isna().any():
            raise ValueError("available_from contains null/unparseable values")
        fingerprint = _schema_fingerprint(prepared)

        existing = self._connection.execute(
            """
            SELECT source_sha256, rows, schema_fingerprint
            FROM __mf_pit_snapshots
            WHERE dataset=? AND snapshot_id=?
            """,
            [dataset, snapshot_id],
        ).fetchone()
        if existing is not None:
            same = (
                str(existing[0]) == source_sha256
                and int(existing[1]) == len(prepared)
                and str(existing[2]) == fingerprint
            )
            if not same:
                raise SnapshotConflictError(
                    f"immutable snapshot conflict for {dataset}/{snapshot_id}"
                )
            return SnapshotReceipt(
                dataset=dataset,
                snapshot_id=snapshot_id,
                source_sha256=source_sha256,
                schema_fingerprint=fingerprint,
                rows=len(prepared),
                idempotent=True,
            )

        if self._table_exists(table):
            canonical_columns = self._base_columns(table)
            if canonical_columns != columns:
                raise SchemaDriftError(
                    f"schema drift for {dataset}: expected {canonical_columns}, got {columns}"
                )

        self._connection.register("__mf_incoming", prepared)
        try:
            self._connection.execute("BEGIN TRANSACTION")
            if not self._table_exists(table):
                create_query = _sql(
                    "CREATE TABLE ",
                    _quoted(table),
                    " AS SELECT *, "
                    "CAST(NULL AS VARCHAR) AS __snapshot_id, "
                    "CAST(NULL AS VARCHAR) AS __source_sha256, "
                    "CAST(NULL AS TIMESTAMPTZ) AS __retrieved_at "
                    "FROM __mf_incoming WHERE FALSE",
                )
                self._connection.execute(create_query)
            insert_query = _sql(
                "INSERT INTO ",
                _quoted(table),
                " SELECT *, ?, ?, ? FROM __mf_incoming",
            )
            self._connection.execute(
                insert_query,
                [snapshot_id, source_sha256, retrieved.to_pydatetime()],
            )
            self._connection.execute(
                """
                INSERT INTO __mf_pit_snapshots
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    dataset,
                    snapshot_id,
                    source_sha256,
                    retrieved.to_pydatetime(),
                    len(prepared),
                    fingerprint,
                ],
            )
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        finally:
            self._connection.unregister("__mf_incoming")

        return SnapshotReceipt(
            dataset=dataset,
            snapshot_id=snapshot_id,
            source_sha256=source_sha256,
            schema_fingerprint=fingerprint,
            rows=len(prepared),
            idempotent=False,
        )

    def snapshots(self, dataset: str | None = None) -> pd.DataFrame:
        if dataset is None:
            return self._connection.execute(
                "SELECT * FROM __mf_pit_snapshots ORDER BY dataset, retrieved_at, snapshot_id"
            ).df()
        dataset = _identifier(dataset, kind="dataset")
        return self._connection.execute(
            """
            SELECT * FROM __mf_pit_snapshots
            WHERE dataset=?
            ORDER BY retrieved_at, snapshot_id
            """,
            [dataset],
        ).df()

    def history_asof(
        self,
        dataset: str,
        cutoff: datetime | pd.Timestamp | str,
        *,
        available_from_column: str = "available_from",
    ) -> pd.DataFrame:
        dataset = _identifier(dataset, kind="dataset")
        table = self._table_name(dataset)
        if not self._table_exists(table):
            raise KeyError(f"unknown PIT dataset: {dataset}")
        available_from_column = _identifier(available_from_column, kind="column")
        columns = self._base_columns(table)
        if available_from_column not in columns:
            raise ValueError(f"dataset has no {available_from_column!r} column")
        cutoff_ts = _utc_timestamp(cutoff, field="cutoff")
        select = ", ".join(_quoted(column) for column in columns)
        query = _sql(
            "SELECT ",
            select,
            " FROM ",
            _quoted(table),
            " WHERE ",
            _quoted(available_from_column),
            " <= ? ORDER BY ",
            _quoted(available_from_column),
        )
        return self._connection.execute(query, [cutoff_ts.to_pydatetime()]).df()

    def latest_asof(
        self,
        dataset: str,
        cutoff: datetime | pd.Timestamp | str,
        *,
        partition_by: Iterable[str],
        available_from_column: str = "available_from",
    ) -> pd.DataFrame:
        dataset = _identifier(dataset, kind="dataset")
        table = self._table_name(dataset)
        if not self._table_exists(table):
            raise KeyError(f"unknown PIT dataset: {dataset}")
        available_from_column = _identifier(available_from_column, kind="column")
        keys = [_identifier(column, kind="column") for column in partition_by]
        if not keys:
            raise ValueError("partition_by must not be empty")
        columns = self._base_columns(table)
        missing = set(keys + [available_from_column]) - set(columns)
        if missing:
            raise ValueError(f"unknown PIT columns: {sorted(missing)}")
        cutoff_ts = _utc_timestamp(cutoff, field="cutoff")
        select = ", ".join(_quoted(column) for column in columns)
        partition = ", ".join(_quoted(column) for column in keys)
        ordering = _sql(
            _quoted(available_from_column),
            " DESC, __retrieved_at DESC, __snapshot_id DESC",
        )
        order_output = ", ".join(_quoted(column) for column in keys)
        query = _sql(
            "SELECT ",
            select,
            " FROM ",
            _quoted(table),
            " WHERE ",
            _quoted(available_from_column),
            " <= ? QUALIFY ROW_NUMBER() OVER (PARTITION BY ",
            partition,
            " ORDER BY ",
            ordering,
            ") = 1 ORDER BY ",
            order_output,
        )
        return self._connection.execute(query, [cutoff_ts.to_pydatetime()]).df()

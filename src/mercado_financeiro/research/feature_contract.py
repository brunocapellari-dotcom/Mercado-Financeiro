from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class FeatureField:
    name: str
    semantic_type: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("feature field name is required")
        if self.semantic_type not in {"numeric", "string", "boolean", "datetime"}:
            raise ValueError(f"unsupported semantic_type: {self.semantic_type}")


@dataclass(frozen=True)
class FeatureSchema:
    name: str
    version: str
    entity_keys: tuple[str, ...]
    event_timestamp_column: str
    fields: tuple[FeatureField, ...]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("feature schema name/version are required")
        if not self.entity_keys or any(not key.strip() for key in self.entity_keys):
            raise ValueError("at least one entity key is required")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("feature field names must be unique")
        reserved = set(self.entity_keys) | {self.event_timestamp_column}
        if reserved & set(names):
            raise ValueError("feature fields cannot shadow entity/time columns")

    def digest(self) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "entity_keys": list(self.entity_keys),
            "event_timestamp_column": self.event_timestamp_column,
            "fields": [(field.name, field.semantic_type) for field in self.fields],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureSnapshotManifest:
    schema_sha256: str
    content_sha256: str
    row_count: int
    first_event_at: datetime | None
    last_event_at: datetime | None
    as_of_cutoff: datetime
    parent_sha256: tuple[str, ...]
    code_commit_sha: str


def _semantic_matches(series: pd.Series, semantic_type: str) -> bool:
    if semantic_type == "numeric":
        return pd.api.types.is_numeric_dtype(series.dtype)
    if semantic_type == "boolean":
        return pd.api.types.is_bool_dtype(series.dtype)
    if semantic_type == "datetime":
        return pd.api.types.is_datetime64_any_dtype(series.dtype)
    if semantic_type == "string":
        return pd.api.types.is_string_dtype(series.dtype) or series.dtype == object
    return False


def validate_feature_frame(frame: pd.DataFrame, schema: FeatureSchema) -> None:
    required = set(schema.entity_keys) | {schema.event_timestamp_column} | {
        field.name for field in schema.fields
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing feature columns: {sorted(missing)}")
    event = pd.to_datetime(frame[schema.event_timestamp_column], errors="coerce", utc=True)
    if event.isna().any():
        raise ValueError("feature event timestamps must be valid")
    if frame[list(schema.entity_keys)].isna().any().any():
        raise ValueError("feature entity keys cannot be null")
    if frame.duplicated([*schema.entity_keys, schema.event_timestamp_column]).any():
        raise ValueError("duplicate feature entity/timestamp rows")
    for field in schema.fields:
        if not _semantic_matches(frame[field.name], field.semantic_type):
            raise TypeError(
                f"feature {field.name!r} does not match semantic type {field.semantic_type!r}"
            )


def assert_feature_cutoff(
    frame: pd.DataFrame,
    *,
    event_timestamp_column: str,
    source_max_timestamp_column: str,
) -> None:
    if event_timestamp_column not in frame or source_max_timestamp_column not in frame:
        raise ValueError("event/source max timestamp columns are required")
    event = pd.to_datetime(frame[event_timestamp_column], errors="coerce", utc=True)
    source = pd.to_datetime(frame[source_max_timestamp_column], errors="coerce", utc=True)
    bad = source.notna() & event.notna() & (source >= event)
    if bad.any():
        raise RuntimeError(f"feature look-ahead detected on {int(bad.sum())} rows")


def assert_training_serving_parity(
    training: pd.DataFrame,
    serving: pd.DataFrame,
    schema: FeatureSchema,
) -> None:
    validate_feature_frame(training, schema)
    validate_feature_frame(serving, schema)
    ordered = [*schema.entity_keys, schema.event_timestamp_column, *(field.name for field in schema.fields)]
    train_signature = tuple((column, str(training[column].dtype)) for column in ordered)
    serving_signature = tuple((column, str(serving[column].dtype)) for column in ordered)
    if train_signature != serving_signature:
        raise RuntimeError(
            "training/serving feature dtype mismatch: "
            f"training={train_signature}, serving={serving_signature}"
        )


def build_feature_snapshot_manifest(
    frame: pd.DataFrame,
    schema: FeatureSchema,
    *,
    as_of_cutoff: datetime,
    parent_sha256: Iterable[str],
    code_commit_sha: str,
) -> FeatureSnapshotManifest:
    validate_feature_frame(frame, schema)
    if as_of_cutoff.tzinfo is None or as_of_cutoff.utcoffset() is None:
        raise ValueError("as_of_cutoff must be timezone-aware")
    parents = tuple(parent_sha256)
    for digest in parents:
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("parent_sha256 values must be lowercase SHA-256 digests")

    columns = [*schema.entity_keys, schema.event_timestamp_column, *(field.name for field in schema.fields)]
    canonical = frame[columns].copy()
    canonical[schema.event_timestamp_column] = pd.to_datetime(
        canonical[schema.event_timestamp_column], utc=True
    )
    canonical = canonical.sort_values([*schema.entity_keys, schema.event_timestamp_column], kind="stable")
    hashed = pd.util.hash_pandas_object(canonical, index=False, categorize=True).values.tobytes()
    content_digest = sha256(hashed).hexdigest()
    events = canonical[schema.event_timestamp_column]
    first = events.min().to_pydatetime() if len(events) else None
    last = events.max().to_pydatetime() if len(events) else None
    cutoff_utc = as_of_cutoff.astimezone(timezone.utc)
    if last is not None and last > cutoff_utc:
        raise RuntimeError("feature snapshot contains events after as_of_cutoff")
    return FeatureSnapshotManifest(
        schema_sha256=schema.digest(),
        content_sha256=content_digest,
        row_count=len(canonical),
        first_event_at=first,
        last_event_at=last,
        as_of_cutoff=cutoff_utc,
        parent_sha256=parents,
        code_commit_sha=code_commit_sha,
    )

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

_ID = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

class CloudLayer(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    FEATURES = "features"
    RESEARCH = "research"

@dataclass(frozen=True)
class CloudDatasetSpec:
    layer: CloudLayer
    dataset_id: str
    description: str
    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.dataset_id):
            raise ValueError(f"invalid BigQuery dataset_id: {self.dataset_id!r}")
        if not self.description.strip():
            raise ValueError("dataset description is required")

@dataclass(frozen=True)
class CloudTableSpec:
    layer: CloudLayer
    table_id: str
    partition_field: str | None
    cluster_fields: tuple[str, ...]
    append_only: bool
    pit_required: bool
    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.table_id):
            raise ValueError(f"invalid BigQuery table_id: {self.table_id!r}")
        fields = (() if self.partition_field is None else (self.partition_field,)) + self.cluster_fields
        if any(not _ID.fullmatch(field) for field in fields):
            raise ValueError("partition/cluster fields must be safe identifiers")
        if len(self.cluster_fields) > 4 or len(set(self.cluster_fields)) != len(self.cluster_fields):
            raise ValueError("invalid BigQuery cluster field configuration")

def canonical_cloud_datasets(prefix: str = "mf") -> tuple[CloudDatasetSpec, ...]:
    if not _ID.fullmatch(prefix):
        raise ValueError("dataset prefix must be a safe identifier")
    return tuple(
        CloudDatasetSpec(layer, f"{prefix}_{layer.value}", f"Mercado Financeiro {layer.value} canonical layer")
        for layer in CloudLayer
    )

def canonical_cloud_tables() -> tuple[CloudTableSpec, ...]:
    return (
        CloudTableSpec(CloudLayer.RAW, "source_manifest", "retrieved_date", ("source_name",), True, False),
        CloudTableSpec(CloudLayer.RAW, "snapshot_receipt", "retrieved_date", ("dataset", "snapshot_id"), True, False),
        CloudTableSpec(CloudLayer.NORMALIZED, "security_master", "available_date", ("security_id", "listing_id"), True, True),
        CloudTableSpec(CloudLayer.NORMALIZED, "market_quotes", "trade_date", ("security_id",), True, True),
        CloudTableSpec(CloudLayer.NORMALIZED, "corporate_actions", "available_date", ("security_id", "action_type"), True, True),
        CloudTableSpec(CloudLayer.NORMALIZED, "fundamentals", "available_date", ("issuer_id", "metric"), True, True),
        CloudTableSpec(CloudLayer.NORMALIZED, "macro", "available_date", ("series_id",), True, True),
        CloudTableSpec(CloudLayer.FEATURES, "feature_mart", "feature_date", ("security_id",), True, True),
        CloudTableSpec(CloudLayer.RESEARCH, "experiment_run", "created_date", ("strategy_id",), True, False),
        CloudTableSpec(CloudLayer.RESEARCH, "tournament_result", "created_date", ("strategy_id",), True, False),
    )

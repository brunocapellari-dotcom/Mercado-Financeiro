from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
import re
from typing import Mapping, Protocol

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


class ExperimentStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("experiment values must be finite")
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda x: str(x[0]))}
    raise TypeError(f"unsupported experiment value type: {type(value).__name__}")


def _mapping_tuple(values: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    return tuple((str(key), _canonical_value(value)) for key, value in sorted(values.items()))


@dataclass(frozen=True)
class ExperimentRunManifest:
    """Immutable lineage record for one research/training/backtest execution."""

    run_id: str
    experiment_name: str
    code_commit_sha: str
    dataset_manifest_sha256: str
    feature_manifest_sha256: str
    started_at: datetime
    ended_at: datetime
    status: ExperimentStatus
    parameters: tuple[tuple[str, object], ...] = ()
    metrics: tuple[tuple[str, float], ...] = ()
    artifact_sha256: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    parent_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.experiment_name.strip():
            raise ValueError("run_id and experiment_name are required")
        if not _COMMIT_RE.fullmatch(self.code_commit_sha.lower()):
            raise ValueError("code_commit_sha must be a hexadecimal commit identifier")
        for name in ("dataset_manifest_sha256", "feature_manifest_sha256"):
            if not _SHA256_RE.fullmatch(getattr(self, name).lower()):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        for digest in self.artifact_sha256:
            if not _SHA256_RE.fullmatch(digest.lower()):
                raise ValueError("artifact_sha256 contains invalid digest")
        for name in ("started_at", "ended_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        if len({name for name, _ in self.parameters}) != len(self.parameters):
            raise ValueError("parameter names must be unique")
        if len({name for name, _ in self.metrics}) != len(self.metrics):
            raise ValueError("metric names must be unique")
        for _, value in self.metrics:
            if not math.isfinite(float(value)):
                raise ValueError("metrics must be finite")

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        experiment_name: str,
        code_commit_sha: str,
        dataset_manifest_sha256: str,
        feature_manifest_sha256: str,
        started_at: datetime,
        ended_at: datetime,
        status: ExperimentStatus,
        parameters: Mapping[str, object] | None = None,
        metrics: Mapping[str, float] | None = None,
        artifact_sha256: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        parent_run_id: str | None = None,
    ) -> "ExperimentRunManifest":
        return cls(
            run_id=run_id,
            experiment_name=experiment_name,
            code_commit_sha=code_commit_sha.lower(),
            dataset_manifest_sha256=dataset_manifest_sha256.lower(),
            feature_manifest_sha256=feature_manifest_sha256.lower(),
            started_at=started_at.astimezone(timezone.utc),
            ended_at=ended_at.astimezone(timezone.utc),
            status=status,
            parameters=_mapping_tuple(parameters or {}),
            metrics=tuple((str(k), float(v)) for k, v in sorted((metrics or {}).items())),
            artifact_sha256=tuple(d.lower() for d in artifact_sha256),
            evidence_refs=tuple(evidence_refs),
            parent_run_id=parent_run_id,
        )

    def digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "experiment_name": self.experiment_name,
            "code_commit_sha": self.code_commit_sha,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "feature_manifest_sha256": self.feature_manifest_sha256,
            "started_at": self.started_at.astimezone(timezone.utc).isoformat(),
            "ended_at": self.ended_at.astimezone(timezone.utc).isoformat(),
            "status": self.status.value,
            "parameters": list(self.parameters),
            "metrics": list(self.metrics),
            "artifact_sha256": list(self.artifact_sha256),
            "evidence_refs": list(self.evidence_refs),
            "parent_run_id": self.parent_run_id,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(canonical.encode("utf-8")).hexdigest()


class ExperimentStore(Protocol):
    durable: bool

    def put_new(self, manifest: ExperimentRunManifest) -> str:
        ...

    def get(self, run_id: str) -> tuple[ExperimentRunManifest, str] | None:
        ...


class InMemoryExperimentStore:
    durable = False

    def __init__(self) -> None:
        self._runs: dict[str, tuple[ExperimentRunManifest, str]] = {}

    def put_new(self, manifest: ExperimentRunManifest) -> str:
        if manifest.run_id in self._runs:
            raise ValueError("experiment run_id is immutable and already exists")
        digest = manifest.digest()
        self._runs[manifest.run_id] = (manifest, digest)
        return digest

    def get(self, run_id: str) -> tuple[ExperimentRunManifest, str] | None:
        return self._runs.get(run_id)


class ExperimentRecorder:
    def __init__(self, store: ExperimentStore | None = None) -> None:
        self._store = store or InMemoryExperimentStore()

    @property
    def durable(self) -> bool:
        return bool(getattr(self._store, "durable", False))

    def record(self, manifest: ExperimentRunManifest) -> str:
        return self._store.put_new(manifest)

    def get(self, run_id: str) -> ExperimentRunManifest:
        record = self._store.get(run_id)
        if record is None:
            raise KeyError(run_id)
        manifest, stored_digest = record
        if manifest.digest() != stored_digest:
            raise RuntimeError("experiment manifest integrity failure")
        return manifest

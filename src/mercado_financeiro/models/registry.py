from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Mapping, Protocol

from mercado_financeiro.architecture import evaluate_live_promotion

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


class ModelStage(str, Enum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"
    RETIRED = "retired"


@dataclass(frozen=True)
class ModelManifest:
    model_name: str
    version: str
    artifact_sha256: str
    code_commit_sha: str
    dataset_manifest_sha256: str
    feature_schema_sha256: str
    training_start: datetime
    training_end: datetime
    as_of_cutoff: datetime
    created_at: datetime
    metrics: tuple[tuple[str, float], ...] = ()
    parent_version: str | None = None

    def __post_init__(self) -> None:
        if not self.model_name.strip() or not self.version.strip():
            raise ValueError("model_name and version are required")
        for field_name in ("artifact_sha256", "dataset_manifest_sha256", "feature_schema_sha256"):
            value = getattr(self, field_name).lower()
            if not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256")
        if not _COMMIT_RE.fullmatch(self.code_commit_sha.lower()):
            raise ValueError("code_commit_sha must be a hexadecimal commit identifier")
        for name in ("training_start", "training_end", "as_of_cutoff", "created_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.training_end < self.training_start:
            raise ValueError("training_end cannot precede training_start")
        if self.training_end > self.as_of_cutoff:
            raise ValueError("training data cannot extend beyond as_of_cutoff")
        if self.as_of_cutoff > self.created_at:
            raise ValueError("as_of_cutoff cannot be after manifest creation")
        metric_names = [name for name, _ in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("metric names must be unique")

    @property
    def key(self) -> str:
        return f"{self.model_name}:{self.version}"

    def digest(self) -> str:
        payload = {
            "model_name": self.model_name,
            "version": self.version,
            "artifact_sha256": self.artifact_sha256,
            "code_commit_sha": self.code_commit_sha,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "feature_schema_sha256": self.feature_schema_sha256,
            "training_start": self.training_start.astimezone(timezone.utc).isoformat(),
            "training_end": self.training_end.astimezone(timezone.utc).isoformat(),
            "as_of_cutoff": self.as_of_cutoff.astimezone(timezone.utc).isoformat(),
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "metrics": list(self.metrics),
            "parent_version": self.parent_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelVersionState:
    manifest: ModelManifest
    manifest_sha256: str
    stage: ModelStage = ModelStage.CANDIDATE
    stage_changed_at: datetime | None = None


class ModelRegistryStore(Protocol):
    durable: bool

    def put_new(self, state: ModelVersionState) -> None:
        ...

    def get(self, key: str) -> ModelVersionState | None:
        ...

    def update_stage(self, key: str, stage: ModelStage, changed_at: datetime) -> ModelVersionState:
        ...

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        ...

    def resolve_alias(self, model_name: str, alias: str) -> str | None:
        ...


class InMemoryModelRegistryStore:
    durable = False

    def __init__(self) -> None:
        self._states: dict[str, ModelVersionState] = {}
        self._aliases: dict[tuple[str, str], str] = {}

    def put_new(self, state: ModelVersionState) -> None:
        if state.manifest.key in self._states:
            raise ValueError("model version is immutable and already registered")
        self._states[state.manifest.key] = state

    def get(self, key: str) -> ModelVersionState | None:
        return self._states.get(key)

    def update_stage(self, key: str, stage: ModelStage, changed_at: datetime) -> ModelVersionState:
        current = self._states.get(key)
        if current is None:
            raise KeyError(key)
        updated = replace(current, stage=stage, stage_changed_at=changed_at)
        self._states[key] = updated
        return updated

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        self._aliases[(model_name, alias)] = version

    def resolve_alias(self, model_name: str, alias: str) -> str | None:
        return self._aliases.get((model_name, alias))


_STAGE_ORDER = {
    ModelStage.CANDIDATE: 0,
    ModelStage.VALIDATED: 1,
    ModelStage.PAPER: 2,
    ModelStage.SHADOW: 3,
    ModelStage.LIVE: 4,
    ModelStage.RETIRED: 5,
}


class ModelRegistry:
    """Immutable model/version lineage with fail-closed stage promotion."""

    def __init__(self, store: ModelRegistryStore | None = None) -> None:
        self._store = store or InMemoryModelRegistryStore()

    @property
    def durable(self) -> bool:
        return bool(getattr(self._store, "durable", False))

    def register(self, manifest: ModelManifest) -> ModelVersionState:
        state = ModelVersionState(manifest=manifest, manifest_sha256=manifest.digest())
        self._store.put_new(state)
        return state

    def get(self, model_name: str, version: str) -> ModelVersionState:
        state = self._store.get(f"{model_name}:{version}")
        if state is None:
            raise KeyError(f"unknown model version: {model_name}:{version}")
        if state.manifest.digest() != state.manifest_sha256:
            raise RuntimeError("model manifest integrity failure")
        return state

    def promote(
        self,
        model_name: str,
        version: str,
        target: ModelStage,
        *,
        gates: Mapping[str, bool | None],
        changed_at: datetime | None = None,
    ) -> ModelVersionState:
        current = self.get(model_name, version)
        if current.stage is ModelStage.RETIRED:
            raise RuntimeError("retired model versions cannot be reactivated")
        if target is current.stage:
            return current
        if target is not ModelStage.RETIRED:
            expected = _STAGE_ORDER[current.stage] + 1
            if _STAGE_ORDER[target] != expected:
                raise RuntimeError(f"model stage cannot skip: {current.stage.value} -> {target.value}")
            self._assert_stage_gates(target, gates)
        ts = changed_at or datetime.now(timezone.utc)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        return self._store.update_stage(current.manifest.key, target, ts.astimezone(timezone.utc))

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        if not alias.strip():
            raise ValueError("alias is required")
        self.get(model_name, version)
        self._store.set_alias(model_name, alias, version)

    def resolve_alias(self, model_name: str, alias: str) -> ModelVersionState:
        version = self._store.resolve_alias(model_name, alias)
        if version is None:
            raise KeyError(f"unknown alias: {model_name}@{alias}")
        return self.get(model_name, version)

    @staticmethod
    def _assert_stage_gates(target: ModelStage, gates: Mapping[str, bool | None]) -> None:
        requirements: dict[ModelStage, tuple[str, ...]] = {
            ModelStage.VALIDATED: ("backtest", "walk_forward"),
            ModelStage.PAPER: ("backtest", "walk_forward", "risk_validation"),
            ModelStage.SHADOW: ("backtest", "walk_forward", "paper", "risk_validation"),
        }
        if target is ModelStage.LIVE:
            result = evaluate_live_promotion(gates)
            if not result.approved:
                raise RuntimeError(
                    "live model promotion blocked: missing="
                    f"{result.missing}, failed={result.failed}"
                )
            return
        missing = tuple(name for name in requirements.get(target, ()) if gates.get(name) is not True)
        if missing:
            raise RuntimeError(f"model promotion blocked; required gates not green: {missing}")

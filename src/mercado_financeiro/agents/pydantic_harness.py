from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
from typing import Any

from .governance import PydanticHarnessProfile, missing_harness_capabilities


class HarnessCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class HarnessCapabilityRegistry:
    version: str
    Planning: type[Any]
    SubAgents: type[Any]
    Memory: type[Any]
    SpendLimits: type[Any]
    TrajectoryJudge: type[Any]
    DynamicWorkflow: type[Any]


def load_pydantic_harness_registry() -> HarnessCapabilityRegistry:
    """Load the pinned Harness adapter surface lazily.

    Pydantic AI Harness remains outside the deterministic trading core. Its 0.x
    API is isolated here so an upstream minor change cannot silently alter the
    financial research-agent boundary.
    """

    try:
        module = import_module("pydantic_ai_harness")
    except ImportError as exc:
        raise HarnessCompatibilityError(
            "Pydantic AI Harness is optional; install the 'agents' project extra"
        ) from exc

    missing = missing_harness_capabilities(module, PydanticHarnessProfile())
    if missing:
        raise HarnessCompatibilityError(
            "Pydantic AI Harness capability drift: " + ",".join(missing)
        )

    try:
        version = metadata.version("pydantic-ai-harness")
    except metadata.PackageNotFoundError as exc:
        raise HarnessCompatibilityError(
            "pydantic-ai-harness package metadata unavailable"
        ) from exc

    parts = version.split(".")
    if len(parts) < 2 or parts[0] != "0" or parts[1] != "32":
        raise HarnessCompatibilityError(
            f"unsupported pydantic-ai-harness minor: {version}; expected 0.32.x"
        )

    return HarnessCapabilityRegistry(
        version=version,
        Planning=module.Planning,
        SubAgents=module.SubAgents,
        Memory=module.Memory,
        SpendLimits=module.SpendLimits,
        TrajectoryJudge=module.TrajectoryJudge,
        DynamicWorkflow=module.DynamicWorkflow,
    )

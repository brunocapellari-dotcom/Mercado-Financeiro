from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping, Protocol


def digest_result(value: object) -> str:
    """Hash an agent result without putting raw financial content into telemetry."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AgentTrace:
    trace_id: str
    span_id: str
    operation: str
    model: str | None = None
    tool_name: str | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    error_type: str | None = None
    result_digest: str | None = None
    regression_dataset: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id.strip() or not self.span_id.strip():
            raise ValueError("trace_id and span_id are required")
        if not self.operation.strip():
            raise ValueError("operation is required")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd cannot be negative")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")


class AgentTraceSink(Protocol):
    def emit(self, trace: AgentTrace) -> None:
        ...


class InMemoryAgentTraceSink:
    """Test/reference sink. Production may export the same schema over OTLP."""

    def __init__(self) -> None:
        self._traces: list[AgentTrace] = []

    def emit(self, trace: AgentTrace) -> None:
        self._traces.append(trace)

    @property
    def traces(self) -> tuple[AgentTrace, ...]:
        return tuple(self._traces)


def otel_attributes(trace: AgentTrace) -> Mapping[str, str | int | float | bool]:
    """Return backend-neutral OpenTelemetry attributes.

    Project-owned mf.* keys are stable even if Phoenix/OpenInference/Pydantic
    instrumentation changes. Export adapters may additionally map these fields to
    current OpenInference semantic conventions.
    """

    attrs: dict[str, str | int | float | bool] = {
        "mf.agent.operation": trace.operation,
    }
    optional = {
        "mf.agent.model": trace.model,
        "mf.agent.tool.name": trace.tool_name,
        "mf.agent.cost_usd": trace.cost_usd,
        "mf.agent.latency_ms": trace.latency_ms,
        "mf.agent.error_type": trace.error_type,
        "mf.agent.result_sha256": trace.result_digest,
        "mf.agent.regression_dataset": trace.regression_dataset,
    }
    attrs.update({key: value for key, value in optional.items() if value is not None})
    return attrs

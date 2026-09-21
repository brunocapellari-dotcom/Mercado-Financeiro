from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class EngineParitySnapshot:
    engine: str
    event_stream_sha256: str
    positions: Mapping[str, Decimal]
    cash: Decimal
    realized_pnl: Decimal
    cumulative_fees: Decimal
    executions: int
    risk_rejections: int

    def __post_init__(self) -> None:
        if not self.engine.strip():
            raise ValueError("engine is required")
        digest = self.event_stream_sha256.strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("event_stream_sha256 must be a lowercase SHA-256 digest")
        if self.cumulative_fees < 0:
            raise ValueError("cumulative_fees cannot be negative")
        if self.executions < 0 or self.risk_rejections < 0:
            raise ValueError("execution counters cannot be negative")


@dataclass(frozen=True)
class EngineParityResult:
    passed: bool
    mismatches: tuple[str, ...]


def compare_engine_snapshots(
    reference: EngineParitySnapshot,
    candidate: EngineParitySnapshot,
    *,
    position_tolerance: Decimal = Decimal("0"),
    monetary_tolerance: Decimal = Decimal("0.01"),
) -> EngineParityResult:
    """Compare normalized outputs from the canonical engine and a candidate engine."""

    if position_tolerance < 0 or monetary_tolerance < 0:
        raise ValueError("parity tolerances cannot be negative")

    mismatches: list[str] = []
    if reference.event_stream_sha256 != candidate.event_stream_sha256:
        mismatches.append("event_stream_sha256")

    for instrument in sorted(set(reference.positions) | set(candidate.positions)):
        left = reference.positions.get(instrument, Decimal("0"))
        right = candidate.positions.get(instrument, Decimal("0"))
        if abs(left - right) > position_tolerance:
            mismatches.append(f"position:{instrument}")

    for name in ("cash", "realized_pnl", "cumulative_fees"):
        left = getattr(reference, name)
        right = getattr(candidate, name)
        if abs(left - right) > monetary_tolerance:
            mismatches.append(name)

    if reference.executions != candidate.executions:
        mismatches.append("executions")
    if reference.risk_rejections != candidate.risk_rejections:
        mismatches.append("risk_rejections")

    return EngineParityResult(passed=not mismatches, mismatches=tuple(mismatches))

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    category: str
    state: HealthState
    checked_at: datetime
    last_success_at: datetime | None = None
    details: str | None = None

    def __post_init__(self) -> None:
        if not self.component.strip() or not self.category.strip():
            raise ValueError("component and category are required")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.last_success_at is not None:
            if self.last_success_at.tzinfo is None or self.last_success_at.utcoffset() is None:
                raise ValueError("last_success_at must be timezone-aware")
            if self.last_success_at > self.checked_at:
                raise ValueError("last_success_at cannot be after checked_at")


@dataclass(frozen=True)
class SystemHealthReport:
    checked_at: datetime
    state: HealthState
    components: tuple[ComponentHealth, ...]
    failed: tuple[str, ...]
    degraded: tuple[str, ...]


def evaluate_freshness_health(
    *,
    component: str,
    category: str,
    checked_at: datetime,
    last_success_at: datetime | None,
    max_age: timedelta,
    failed: bool = False,
    details: str | None = None,
) -> ComponentHealth:
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    if failed:
        state = HealthState.FAILED
    elif last_success_at is None:
        state = HealthState.UNKNOWN
    elif checked_at - last_success_at > max_age:
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY
    return ComponentHealth(
        component=component,
        category=category,
        state=state,
        checked_at=checked_at,
        last_success_at=last_success_at,
        details=details,
    )


def build_system_health(
    components: Iterable[ComponentHealth],
    *,
    checked_at: datetime,
) -> SystemHealthReport:
    materialized = tuple(components)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("checked_at must be timezone-aware")
    failed = tuple(sorted(c.component for c in materialized if c.state is HealthState.FAILED))
    degraded = tuple(
        sorted(
            c.component
            for c in materialized
            if c.state in {HealthState.DEGRADED, HealthState.UNKNOWN}
        )
    )
    if failed:
        state = HealthState.FAILED
    elif degraded:
        state = HealthState.DEGRADED
    else:
        state = HealthState.HEALTHY
    return SystemHealthReport(
        checked_at=checked_at,
        state=state,
        components=materialized,
        failed=failed,
        degraded=degraded,
    )

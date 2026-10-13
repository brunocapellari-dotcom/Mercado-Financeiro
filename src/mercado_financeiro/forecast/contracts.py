from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    model_id: str
    model_version: str
    instrument: str
    target: str
    value: float
    generated_at: datetime
    valid_until: datetime
    horizon_seconds: int
    lower_bound: float | None = None
    upper_bound: float | None = None
    source_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("generated_at", self.generated_at), ("valid_until", self.valid_until)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.valid_until <= self.generated_at:
            raise ValueError("valid_until must be after generated_at")
        if self.horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be positive")
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                raise ValueError("lower_bound cannot exceed upper_bound")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class SignalProposal:
    signal_id: str
    strategy_id: str
    instrument: str
    direction: SignalDirection
    strength: float
    generated_at: datetime
    expires_at: datetime
    forecast_ids: tuple[str, ...]
    rationale: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("generated_at", self.generated_at), ("expires_at", self.expires_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.expires_at <= self.generated_at:
            raise ValueError("expires_at must be after generated_at")
        if not -1 <= self.strength <= 1:
            raise ValueError("strength must be between -1 and 1")

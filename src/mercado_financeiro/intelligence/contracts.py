from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mercado_financeiro.architecture import AIRole


@dataclass(frozen=True)
class IntelligenceArtifact:
    role: AIRole
    artifact_id: str
    generated_at: datetime
    as_of: datetime
    summary: str
    evidence_ids: tuple[str, ...]
    confidence: float | None = None

    def __post_init__(self) -> None:
        for name, value in (("generated_at", self.generated_at), ("as_of", self.as_of)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.as_of > self.generated_at:
            raise ValueError("intelligence cannot be as-of after it was generated")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

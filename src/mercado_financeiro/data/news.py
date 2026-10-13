from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Iterable


@dataclass(frozen=True)
class NewsEvent:
    provider: str
    article_id: str
    published_at: datetime
    received_at: datetime
    headline: str
    source_url: str
    body_digest: str
    entities: tuple[str, ...] = ()
    language: str | None = None
    corrected_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, value in (("published_at", self.published_at), ("received_at", self.received_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.received_at < self.published_at:
            raise ValueError("received_at cannot precede published_at")
        if self.corrected_at is not None:
            if self.corrected_at.tzinfo is None or self.corrected_at.utcoffset() is None:
                raise ValueError("corrected_at must be timezone-aware")
            if self.corrected_at < self.published_at:
                raise ValueError("corrected_at cannot precede published_at")
        if not self.provider.strip() or not self.article_id.strip() or not self.headline.strip():
            raise ValueError("provider/article_id/headline are required")
        if len(self.body_digest) != 64:
            raise ValueError("body_digest must be SHA-256 hex")
        try:
            int(self.body_digest, 16)
        except ValueError as exc:
            raise ValueError("body_digest must be SHA-256 hex") from exc

    @property
    def available_from(self) -> datetime:
        # Information cannot be consumed before our system received it even if
        # the publisher timestamp is earlier.
        return self.received_at


class NewsProvider(ABC):
    """Normalized news boundary; vendor credentials stay inside implementations."""

    name: str

    @abstractmethod
    def poll(self, *, since: datetime) -> Iterable[NewsEvent]:
        ...


def news_body_digest(body: str | bytes) -> str:
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return sha256(payload).hexdigest()

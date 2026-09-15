from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class SourceManifest:
    source_name: str
    source_url: str
    retrieved_at_utc: str
    bytes: int
    sha256: str
    publication_time: str | None = None
    reference_time: str | None = None
    upstream_id: str | None = None
    parser_version: str | None = None
    parent_sha256: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify_payload_digest(payload: bytes, expected_sha256: str) -> str:
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected_sha256 must be a 64-character hex digest")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def build_source_manifest(
    payload: bytes,
    *,
    source_name: str,
    source_url: str,
    retrieved_at: datetime | None = None,
    publication_time: str | None = None,
    reference_time: str | None = None,
    upstream_id: str | None = None,
    parser_version: str | None = None,
    parent_sha256: tuple[str, ...] = (),
) -> SourceManifest:
    if not source_name.strip():
        raise ValueError("source_name is required")
    when = retrieved_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    when = when.astimezone(timezone.utc)
    parents: list[str] = []
    for digest in parent_sha256:
        normalized = digest.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("parent SHA-256 values must be 64-character hex digests")
        parents.append(normalized)
    return SourceManifest(
        source_name=source_name.strip(),
        source_url=source_url,
        retrieved_at_utc=when.isoformat().replace("+00:00", "Z"),
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        publication_time=publication_time,
        reference_time=reference_time,
        upstream_id=upstream_id,
        parser_version=parser_version,
        parent_sha256=tuple(parents),
    )

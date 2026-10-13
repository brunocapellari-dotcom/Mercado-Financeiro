from __future__ import annotations

from datetime import datetime
import re
from mercado_financeiro.security import SourceManifest

_SLUG = re.compile(r"[^a-z0-9._-]+")

def _slug(value: str) -> str:
    normalized = _SLUG.sub("-", value.strip().lower()).strip("-._")
    if not normalized or len(normalized) > 100:
        raise ValueError("source name cannot be converted to a safe object-key slug")
    return normalized

def raw_object_key(manifest: SourceManifest) -> str:
    retrieved = datetime.fromisoformat(manifest.retrieved_at_utc.replace("Z", "+00:00"))
    digest = manifest.sha256.lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("manifest sha256 is invalid")
    return f"raw/{_slug(manifest.source_name)}/{retrieved:%Y/%m/%d}/sha256/{digest[:2]}/{digest}"

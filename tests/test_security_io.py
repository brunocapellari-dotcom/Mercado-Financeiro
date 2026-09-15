from __future__ import annotations

from datetime import datetime, timezone
import io
import zipfile

import pytest

from mercado_financeiro.security import (
    SourceSecurityError,
    build_source_manifest,
    validate_source_url,
    validate_zip_bytes,
    verify_payload_digest,
)


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_source_url_requires_https_and_allowlist():
    assert validate_source_url("https://dados.cvm.gov.br/example.zip")
    with pytest.raises(SourceSecurityError):
        validate_source_url("http://dados.cvm.gov.br/example.zip")
    with pytest.raises(SourceSecurityError):
        validate_source_url("https://example.com/example.zip")
    with pytest.raises(SourceSecurityError):
        validate_source_url("https://user:pass@dados.cvm.gov.br/example.zip")


def test_zip_rejects_traversal_and_absolute_paths():
    with pytest.raises(SourceSecurityError):
        validate_zip_bytes(_zip({"../escape.txt": b"x"}))
    with pytest.raises(SourceSecurityError):
        validate_zip_bytes(_zip({"/absolute.txt": b"x"}))


def test_zip_rejects_expansion_limits():
    payload = _zip({"large.txt": b"A" * 10_000})
    with pytest.raises(SourceSecurityError):
        validate_zip_bytes(payload, max_member_uncompressed=1_000)
    with pytest.raises(SourceSecurityError):
        validate_zip_bytes(payload, max_compression_ratio=2.0)


def test_manifest_is_deterministic_and_digest_verified():
    payload = b"authoritative snapshot"
    manifest = build_source_manifest(
        payload,
        source_name="TEST",
        source_url="https://dados.cvm.gov.br/test",
        retrieved_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        parser_version="1",
    )
    assert manifest.bytes == len(payload)
    assert verify_payload_digest(payload, manifest.sha256) == manifest.sha256
    assert '"source_name":"TEST"' in manifest.to_json()
    with pytest.raises(ValueError):
        verify_payload_digest(payload + b"tamper", manifest.sha256)

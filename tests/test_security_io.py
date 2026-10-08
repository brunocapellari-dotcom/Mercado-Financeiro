from __future__ import annotations

from datetime import datetime, timezone
import io
import urllib.error
import zipfile

import pytest

import mercado_financeiro.security.io as security_io
from mercado_financeiro.security import (
    RetryPolicy,
    SourceSecurityError,
    build_source_manifest,
    download_https_with_retry,
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


def test_retry_recovers_transient_public_source_failure(monkeypatch):
    attempts: list[str] = []

    def fake_download(url, policy=None, *, headers=None):
        attempts.append(url)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)
        return b"official-payload"

    monkeypatch.setattr(security_io, "download_https", fake_download)
    result = download_https_with_retry(
        "https://bvmf.bmfbovespa.com.br/example.zip",
        retry_policy=RetryPolicy(
            attempts=2,
            initial_delay_seconds=0,
            max_delay_seconds=0,
        ),
    )
    assert result == b"official-payload"
    assert len(attempts) == 2


def test_retry_retries_transient_invalid_payload(monkeypatch):
    calls = 0

    def fake_download(url, policy=None, *, headers=None):
        nonlocal calls
        calls += 1
        return b"<html>temporary upstream error</html>" if calls == 1 else _zip({"ok.txt": b"ok"})

    def require_zip(payload: bytes) -> None:
        if not payload.startswith(b"PK"):
            raise OSError("expected ZIP payload")
        validate_zip_bytes(payload)

    monkeypatch.setattr(security_io, "download_https", fake_download)
    result = download_https_with_retry(
        "https://bvmf.bmfbovespa.com.br/example.zip",
        retry_policy=RetryPolicy(
            attempts=2,
            initial_delay_seconds=0,
            max_delay_seconds=0,
        ),
        payload_validator=require_zip,
    )
    assert result.startswith(b"PK")
    assert calls == 2


def test_retry_does_not_mask_permanent_http_or_security_failures(monkeypatch):
    calls = 0

    def permanent_404(url, policy=None, *, headers=None):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(security_io, "download_https", permanent_404)
    with pytest.raises(urllib.error.HTTPError):
        download_https_with_retry(
            "https://dados.cvm.gov.br/missing.zip",
            retry_policy=RetryPolicy(
                attempts=5,
                initial_delay_seconds=0,
                max_delay_seconds=0,
            ),
        )
    assert calls == 1

    def policy_violation(url, policy=None, *, headers=None):
        raise SourceSecurityError("blocked")

    monkeypatch.setattr(security_io, "download_https", policy_violation)
    with pytest.raises(SourceSecurityError):
        download_https_with_retry(
            "https://dados.cvm.gov.br/test.zip",
            retry_policy=RetryPolicy(
                attempts=5,
                initial_delay_seconds=0,
                max_delay_seconds=0,
            ),
        )


def test_source_url_rejects_nonstandard_ports_and_header_injection():
    with pytest.raises(SourceSecurityError, match="port 443"):
        validate_source_url("https://dados.cvm.gov.br:8443/example.zip")
    with pytest.raises(SourceSecurityError):
        security_io._validated_headers({"X-Test\nInjected": "value"})
    with pytest.raises(SourceSecurityError):
        security_io._validated_headers({"X-Test": "value\r\nInjected: yes"})

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import PurePosixPath
import re
import stat
import time
from typing import Callable, Iterable, Mapping
import urllib.error
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

DEFAULT_ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "dados.cvm.gov.br",
        "www.b3.com.br",
        "b3.com.br",
        "sistemaswebb3-listados.b3.com.br",
        "bvmf.bmfbovespa.com.br",
        "api.bcb.gov.br",
        "olinda.bcb.gov.br",
        "dadosabertos.bcb.gov.br",
        "api.anbima.com.br",
        "api-sandbox.anbima.com.br",
        "developers.anbima.com.br",
        "nefin.com.br",
        "www.nefin.com.br",
    }
)

_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "access_token",
        "x-goog-api-key",
    }
)
_FORBIDDEN_CALLER_HEADERS = frozenset({"host", "content-length"})
_ALLOWED_METHODS = frozenset({"GET", "POST"})
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_\x60|~0-9A-Za-z-]{1,128}$")


class SourceSecurityError(ValueError):
    """Raised when an external source violates an ingestion security policy."""


@dataclass(frozen=True)
class DownloadPolicy:
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_SOURCE_HOSTS
    timeout_seconds: float = 30.0
    max_bytes: int = 250_000_000
    user_agent: str = "Mercado-Financeiro/0.1 (+research-ingestion)"

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must not be empty")
        normalized = frozenset(host.strip().lower().rstrip(".") for host in self.allowed_hosts)
        if any(
            not host
            or ":" in host
            or "/" in host
            or "*" in host
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in host)
            for host in normalized
        ):
            raise ValueError("allowed_hosts must contain plain DNS hostnames only")
        object.__setattr__(self, "allowed_hosts", normalized)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for public authoritative data sources.

    Retries are deliberately restricted to transport failures and HTTP statuses
    that can be transient. Security-policy violations and ordinary 4xx responses
    fail immediately. This keeps resilience in one audited path instead of each
    collector implementing subtly different retry behavior.
    """

    attempts: int = 5
    initial_delay_seconds: float = 2.0
    max_delay_seconds: float = 20.0
    multiplier: float = 2.0
    retry_http_statuses: frozenset[int] = frozenset({403, 408, 425, 429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if self.attempts <= 0:
            raise ValueError("attempts must be positive")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be >= 1")
        if not self.retry_http_statuses:
            raise ValueError("retry_http_statuses must not be empty")


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(
        self,
        allowed_hosts: frozenset[str],
        *,
        original_host: str,
        sensitive_request: bool,
    ) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.original_host = original_host
        self.sensitive_request = sensitive_request

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        validate_source_url(newurl, self.allowed_hosts)
        new_host = (urlsplit(newurl).hostname or "").lower().rstrip(".")
        if self.sensitive_request and new_host != self.original_host:
            raise SourceSecurityError(
                "authenticated requests may not redirect credentials to another host"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_source_url(
    url: str,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    if not isinstance(url, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise SourceSecurityError("source URL contains control characters")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise SourceSecurityError("external source must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise SourceSecurityError("credentials embedded in source URLs are forbidden")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise SourceSecurityError("source URL has no hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceSecurityError("source URL has an invalid port") from exc
    if port not in (None, 443):
        raise SourceSecurityError("external HTTPS sources must use port 443")
    allowed = frozenset(h.lower().rstrip(".") for h in (allowed_hosts or DEFAULT_ALLOWED_SOURCE_HOSTS))
    if host not in allowed:
        raise SourceSecurityError(f"source host is not allowlisted: {host}")
    return url


def _validated_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise SourceSecurityError("HTTP header names and values must be strings")
        normalized = name.strip().lower()
        if not _HEADER_NAME_RE.fullmatch(name.strip()):
            raise SourceSecurityError(f"invalid HTTP header name: {name!r}")
        if normalized in _FORBIDDEN_CALLER_HEADERS:
            raise SourceSecurityError(f"caller may not override HTTP header: {name}")
        if len(value) > 8192 or any(ch in value for ch in ("\r", "\n", "\x00")):
            raise SourceSecurityError("invalid or oversized HTTP header value")
        result[name.strip()] = value
    return result


def request_https(
    url: str,
    policy: DownloadPolicy | None = None,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> bytes:
    """Perform a bounded allowlisted HTTPS GET/POST request.

    Sensitive authentication headers stay in memory and are never logged by this
    helper. Authenticated redirects are restricted to the original host so a
    credential cannot be forwarded to a different allowlisted service.
    """

    policy = policy or DownloadPolicy()
    method = method.upper().strip()
    if method not in _ALLOWED_METHODS:
        raise SourceSecurityError(f"HTTP method not permitted for source ingestion: {method}")
    if method == "GET" and body is not None:
        raise SourceSecurityError("GET source requests may not contain a body")
    validate_source_url(url, policy.allowed_hosts)
    parsed = urlsplit(url)
    original_host = (parsed.hostname or "").lower().rstrip(".")
    caller_headers = _validated_headers(headers)
    sensitive_request = any(name.lower() in _SENSITIVE_HEADER_NAMES for name in caller_headers)
    opener = build_opener(
        _ValidatingRedirectHandler(
            policy.allowed_hosts,
            original_host=original_host,
            sensitive_request=sensitive_request,
        )
    )
    request_headers = {"User-Agent": policy.user_agent, **caller_headers}
    request = Request(url, data=body, headers=request_headers, method=method)
    with opener.open(request, timeout=policy.timeout_seconds) as response:
        final_url = response.geturl()
        validate_source_url(final_url, policy.allowed_hosts)
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError as exc:
                raise SourceSecurityError("invalid Content-Length from source") from exc
            if declared < 0 or declared > policy.max_bytes:
                raise SourceSecurityError(
                    f"source response exceeds max_bytes: {declared} > {policy.max_bytes}"
                )
        data = response.read(policy.max_bytes + 1)
    if len(data) > policy.max_bytes:
        raise SourceSecurityError(
            f"source response exceeds max_bytes: > {policy.max_bytes}"
        )
    return data


def download_https(
    url: str,
    policy: DownloadPolicy | None = None,
    *,
    headers: Mapping[str, str] | None = None,
) -> bytes:
    return request_https(url, policy, method="GET", headers=headers)


def download_https_with_retry(
    url: str,
    policy: DownloadPolicy | None = None,
    *,
    retry_policy: RetryPolicy | None = None,
    headers: Mapping[str, str] | None = None,
    payload_validator: Callable[[bytes], None] | None = None,
) -> bytes:
    """Download an allowlisted HTTPS source with bounded exponential backoff.

    A non-empty response is required. Callers may provide a payload validator for
    transport-success/content-failure cases, such as an HTML error page returned
    with HTTP 200 where a ZIP was expected. Validator OSError/ValueError failures
    are retried with the same bounded policy; SourceSecurityError remains fail-closed.
    HTTP 403 is included because several public B3 historical endpoints intermittently
    reject otherwise identical automated requests. The retry never changes host,
    URL, credentials, or canonical source.
    """

    policy = policy or DownloadPolicy()
    retry_policy = retry_policy or RetryPolicy()
    last: BaseException | None = None
    delay = retry_policy.initial_delay_seconds

    for attempt in range(1, retry_policy.attempts + 1):
        try:
            payload = download_https(url, policy, headers=headers)
            if not payload:
                raise OSError("official source returned empty response")
            if payload_validator is not None:
                payload_validator(payload)
            return payload
        except SourceSecurityError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code not in retry_policy.retry_http_statuses:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
            last = exc

        if attempt < retry_policy.attempts and delay > 0:
            time.sleep(min(delay, retry_policy.max_delay_seconds))
        delay = min(delay * retry_policy.multiplier, retry_policy.max_delay_seconds)

    raise RuntimeError(
        f"official source unavailable after {retry_policy.attempts} attempts: {url}"
    ) from last

def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def validate_zip_bytes(
    payload: bytes,
    *,
    max_members: int = 5_000,
    max_total_uncompressed: int = 2_000_000_000,
    max_member_uncompressed: int = 1_000_000_000,
    max_compression_ratio: float = 250.0,
) -> list[zipfile.ZipInfo]:
    """Validate a ZIP without extracting it.

    The function rejects path traversal, absolute paths, symlinks, suspiciously large
    archives and extreme compression ratios. Call it again for every nested ZIP.
    """
    if not payload:
        raise SourceSecurityError("empty ZIP payload")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SourceSecurityError("invalid ZIP payload") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > max_members:
            raise SourceSecurityError(
                f"ZIP member count exceeds limit: {len(infos)} > {max_members}"
            )
        total = 0
        for info in infos:
            name = info.filename
            if "\x00" in name:
                raise SourceSecurityError("ZIP member contains NUL byte")
            normalized = name.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or any(part == ".." for part in path.parts):
                raise SourceSecurityError(f"unsafe ZIP member path: {name!r}")
            if _member_is_symlink(info):
                raise SourceSecurityError(f"ZIP symlink member is forbidden: {name!r}")
            if info.file_size < 0 or info.compress_size < 0:
                raise SourceSecurityError(f"invalid ZIP member sizes: {name!r}")
            if info.file_size > max_member_uncompressed:
                raise SourceSecurityError(
                    f"ZIP member exceeds uncompressed limit: {name!r}"
                )
            total += info.file_size
            if total > max_total_uncompressed:
                raise SourceSecurityError("ZIP total uncompressed size exceeds limit")
            if info.file_size > 0:
                if info.compress_size == 0:
                    raise SourceSecurityError(
                        f"non-empty ZIP member has zero compressed size: {name!r}"
                    )
                ratio = info.file_size / info.compress_size
                if ratio > max_compression_ratio:
                    raise SourceSecurityError(
                        f"ZIP compression ratio exceeds limit for {name!r}: {ratio:.1f}"
                    )
        return infos

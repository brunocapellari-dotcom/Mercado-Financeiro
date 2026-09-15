from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from urllib.parse import urlencode

import pandas as pd

from mercado_financeiro.security import DownloadPolicy, request_https
from .historical import HistoricalDataset, VintageMode


@dataclass(frozen=True)
class AnbimaAccessToken:
    token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("ANBIMA access token is empty")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")


class AnbimaFeedSource:
    """Security-first ANBIMA Feed client.

    Credentials are accepted only at the call boundary and are not persisted in
    the object, logs or provenance records. Production deployment must source
    them from a secret manager in the ingestion identity, never from an LLM or
    research process.
    """

    name = "ANBIMA_FEED"

    def __init__(self, *, sandbox: bool = True, policy: DownloadPolicy | None = None) -> None:
        self.sandbox = bool(sandbox)
        self.base_url = (
            "https://api-sandbox.anbima.com.br" if self.sandbox else "https://api.anbima.com.br"
        )
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"api-sandbox.anbima.com.br", "api.anbima.com.br"}),
            timeout_seconds=30.0,
            max_bytes=100_000_000,
        )

    def obtain_access_token(
        self,
        *,
        client_id: str,
        client_secret: str,
        now: datetime | None = None,
    ) -> AnbimaAccessToken:
        if not client_id or not client_secret:
            raise ValueError("ANBIMA client_id/client_secret are required")
        # Official standard ANBIMA Feed OAuth flow uses the production API host
        # for token issuance. Sandbox applications still receive scoped tokens.
        token_url = "https://api.anbima.com.br/oauth/access-token"
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        body = json.dumps({"grant_type": "client_credentials"}, separators=(",", ":")).encode("utf-8")
        payload = request_https(
            token_url,
            DownloadPolicy(
                allowed_hosts=frozenset({"api.anbima.com.br"}),
                timeout_seconds=self._policy.timeout_seconds,
                max_bytes=1_000_000,
            ),
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=body,
        )
        try:
            response = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid ANBIMA OAuth response") from exc
        token = response.get("access_token") if isinstance(response, dict) else None
        expires_in = response.get("expires_in") if isinstance(response, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("ANBIMA OAuth response has no access_token")
        try:
            lifetime = int(expires_in)
        except (TypeError, ValueError) as exc:
            raise ValueError("ANBIMA OAuth response has invalid expires_in") from exc
        if lifetime <= 0:
            raise ValueError("ANBIMA OAuth token lifetime must be positive")
        issued = now or datetime.now(timezone.utc)
        if issued.tzinfo is None or issued.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        # Small safety margin prevents using a token exactly at expiry.
        return AnbimaAccessToken(token=token, expires_at=issued + timedelta(seconds=max(1, lifetime - 30)))

    def fetch_json(
        self,
        path: str,
        *,
        client_id: str,
        access_token: str,
        params: dict[str, str] | None = None,
        dataset: str,
        retrieved_at: datetime | None = None,
    ) -> HistoricalDataset:
        if not client_id or not access_token:
            raise ValueError("ANBIMA client_id/access_token are required")
        clean_path = path.strip()
        if not clean_path.startswith("/") or "://" in clean_path or ".." in clean_path.split("/"):
            raise ValueError("ANBIMA path must be an absolute API path without traversal")
        query = "?" + urlencode(params) if params else ""
        url = self.base_url + clean_path + query
        payload = request_https(
            url,
            self._policy,
            method="GET",
            headers={
                "client_id": client_id,
                "access_token": access_token,
                "Accept": "application/json",
            },
        )
        retrieved = retrieved_at or datetime.now(timezone.utc)
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        digest = sha256(payload).hexdigest()
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid ANBIMA JSON response") from exc
        if isinstance(decoded, list):
            frame = pd.json_normalize(decoded)
        elif isinstance(decoded, dict):
            # Preserve envelope fields without guessing API-specific pagination.
            candidate = next(
                (value for value in decoded.values() if isinstance(value, list)),
                None,
            )
            frame = pd.json_normalize(candidate if candidate is not None else [decoded])
        else:
            raise ValueError("ANBIMA response must be a JSON object or list")
        frame["source_retrieved_at"] = pd.Timestamp(retrieved).tz_convert("UTC")
        frame["source_sha256"] = digest
        return HistoricalDataset(
            source=self.name,
            dataset=dataset,
            source_url=url,
            retrieved_at=retrieved,
            sha256=digest,
            vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
            frame=frame,
        )

    def healthcheck(self) -> bool:
        return True

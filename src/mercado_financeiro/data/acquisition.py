from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mercado_financeiro.security import RawEvidenceVault, build_source_manifest


@dataclass(frozen=True)
class AcquisitionContext:
    """Shared raw-evidence preservation context for external data collectors."""

    raw_vault: RawEvidenceVault | None = None
    run_id: str | None = None
    commit_sha: str | None = None

    def preserve(
        self,
        payload: bytes,
        *,
        source_name: str,
        source_url: str,
        retrieved_at: datetime,
        upstream_id: str | None = None,
        parser_version: str | None = None,
        publication_time: str | None = None,
        reference_time: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        if self.raw_vault is None:
            return None
        manifest = build_source_manifest(
            payload,
            source_name=source_name,
            source_url=source_url,
            retrieved_at=retrieved_at,
            publication_time=publication_time,
            reference_time=reference_time,
            upstream_id=upstream_id,
            parser_version=parser_version,
            run_id=self.run_id,
            commit_sha=self.commit_sha,
            content_type=content_type,
        )
        return self.raw_vault.store(payload, manifest).receipt_id

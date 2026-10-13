from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class SupplyChainEvidence:
    commit_sha: str
    sbom_sha256: str
    provenance_sha256: str
    signature_verified: bool

    def __post_init__(self) -> None:
        for name, value, size in (
            ("commit_sha", self.commit_sha, 40),
            ("sbom_sha256", self.sbom_sha256, 64),
            ("provenance_sha256", self.provenance_sha256, 64),
        ):
            normalized = value.strip().lower()
            if len(normalized) != size or any(ch not in "0123456789abcdef" for ch in normalized):
                raise ValueError(f"{name} is not a valid hexadecimal digest")


def load_supply_chain_evidence(
    *,
    sbom_path: str | Path,
    provenance_path: str | Path,
    signature_verified: bool,
) -> SupplyChainEvidence:
    sbom = Path(sbom_path).read_bytes()
    provenance_bytes = Path(provenance_path).read_bytes()
    payload = json.loads(provenance_bytes)
    commit = str(payload["source_commit_sha"]).strip().lower()
    sbom_digest = sha256(sbom).hexdigest()
    if payload.get("sbom_sha256") != sbom_digest:
        raise RuntimeError("provenance does not match SBOM digest")
    return SupplyChainEvidence(
        commit_sha=commit,
        sbom_sha256=sbom_digest,
        provenance_sha256=sha256(provenance_bytes).hexdigest(),
        signature_verified=bool(signature_verified),
    )


def assert_deployable_supply_chain(evidence: SupplyChainEvidence) -> None:
    if not evidence.signature_verified:
        raise RuntimeError("deployable artifact requires a verified Sigstore/cosign signature")

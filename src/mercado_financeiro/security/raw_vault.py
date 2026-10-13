from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .provenance import SourceManifest, verify_payload_digest


class RawEvidenceConflictError(RuntimeError):
    """Raised when immutable raw evidence does not match an existing object/receipt."""


@dataclass(frozen=True)
class RawEvidenceReceipt:
    object_sha256: str
    receipt_id: str
    payload_path: Path
    receipt_path: Path
    payload_idempotent: bool
    receipt_idempotent: bool


class RawEvidenceVault:
    """Content-addressed append-only vault for canonical external bytes.

    Payloads are keyed by SHA-256 so identical bytes are stored once. Acquisition
    receipts are keyed by the SHA-256 of the canonical manifest JSON, allowing the
    same upstream payload to be collected at multiple times/runs without losing
    provenance. Existing objects and receipts are never overwritten.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects_root = self.root / "objects" / "sha256"
        self.receipts_root = self.root / "receipts" / "sha256"
        self.objects_root.mkdir(parents=True, exist_ok=True)
        self.receipts_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _object_path(root: Path, digest: str) -> Path:
        return root / digest[:2] / digest[2:4] / digest

    @staticmethod
    def _receipt_path(root: Path, receipt_id: str) -> Path:
        return root / receipt_id[:2] / receipt_id[2:4] / f"{receipt_id}.json"

    @staticmethod
    def _write_immutable(path: Path, content: bytes, *, kind: str) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
            return False
        except FileExistsError:
            existing = path.read_bytes()
            if existing != content:
                raise RawEvidenceConflictError(
                    f"immutable {kind} conflict at {path.as_posix()}"
                )
            return True

    def store(self, payload: bytes, manifest: SourceManifest) -> RawEvidenceReceipt:
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("raw evidence payload must be non-empty bytes")
        if manifest.bytes != len(payload):
            raise ValueError(
                f"manifest byte count mismatch: {manifest.bytes} != {len(payload)}"
            )
        verify_payload_digest(payload, manifest.sha256)

        payload_path = self._object_path(self.objects_root, manifest.sha256)
        payload_idempotent = self._write_immutable(
            payload_path,
            payload,
            kind="payload",
        )

        manifest_bytes = (manifest.to_json() + "\n").encode("utf-8")
        receipt_id = sha256(manifest_bytes).hexdigest()
        receipt_path = self._receipt_path(self.receipts_root, receipt_id)
        receipt_idempotent = self._write_immutable(
            receipt_path,
            manifest_bytes,
            kind="receipt",
        )
        return RawEvidenceReceipt(
            object_sha256=manifest.sha256,
            receipt_id=receipt_id,
            payload_path=payload_path,
            receipt_path=receipt_path,
            payload_idempotent=payload_idempotent,
            receipt_idempotent=receipt_idempotent,
        )

    def read_payload(self, sha256_digest: str) -> bytes:
        digest = sha256_digest.strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("sha256_digest must be a 64-character hexadecimal digest")
        path = self._object_path(self.objects_root, digest)
        if not path.is_file():
            raise KeyError(f"raw evidence object not found: {digest}")
        payload = path.read_bytes()
        verify_payload_digest(payload, digest)
        return payload

    def read_receipt(self, receipt_id: str) -> str:
        value = receipt_id.strip().lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("receipt_id must be a 64-character hexadecimal digest")
        path = self._receipt_path(self.receipts_root, value)
        if not path.is_file():
            raise KeyError(f"raw evidence receipt not found: {value}")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != value:
            raise RawEvidenceConflictError(
                f"raw evidence receipt digest mismatch: {value}"
            )
        return raw.decode("utf-8").rstrip("\n")

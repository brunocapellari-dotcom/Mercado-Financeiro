from datetime import datetime, timezone
import json

import pytest

from mercado_financeiro.security import (
    RawEvidenceConflictError,
    RawEvidenceVault,
    build_source_manifest,
)


def test_raw_evidence_vault_preserves_same_bytes_with_multiple_collection_receipts(tmp_path):
    payload = b"official-source-bytes"
    first_manifest = build_source_manifest(
        payload,
        source_name="CVM",
        source_url="https://dados.cvm.gov.br/example.zip",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        upstream_id="example.zip",
        parser_version="cvm-v1",
        run_id="run-a",
        commit_sha="abcdef1",
        content_type="application/zip",
        license_tag="public-official-source",
    )
    second_manifest = build_source_manifest(
        payload,
        source_name="CVM",
        source_url="https://dados.cvm.gov.br/example.zip",
        retrieved_at=datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        upstream_id="example.zip",
        parser_version="cvm-v1",
        run_id="run-b",
        commit_sha="abcdef2",
        content_type="application/zip",
        license_tag="public-official-source",
    )

    vault = RawEvidenceVault(tmp_path)
    first = vault.store(payload, first_manifest)
    second = vault.store(payload, second_manifest)

    assert first.object_sha256 == second.object_sha256
    assert first.receipt_id != second.receipt_id
    assert not first.payload_idempotent
    assert second.payload_idempotent
    assert not first.receipt_idempotent
    assert not second.receipt_idempotent
    assert vault.read_payload(first.object_sha256) == payload

    first_receipt = json.loads(vault.read_receipt(first.receipt_id))
    second_receipt = json.loads(vault.read_receipt(second.receipt_id))
    assert first_receipt["run_id"] == "run-a"
    assert second_receipt["run_id"] == "run-b"
    assert first_receipt["sha256"] == second_receipt["sha256"]


def test_raw_evidence_vault_is_idempotent_for_identical_receipt(tmp_path):
    payload = b"same"
    manifest = build_source_manifest(
        payload,
        source_name="B3",
        source_url="https://www.b3.com.br/file.zip",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    vault = RawEvidenceVault(tmp_path)
    first = vault.store(payload, manifest)
    second = vault.store(payload, manifest)

    assert not first.payload_idempotent
    assert not first.receipt_idempotent
    assert second.payload_idempotent
    assert second.receipt_idempotent
    assert first.receipt_id == second.receipt_id


def test_raw_evidence_vault_rejects_manifest_payload_mismatch(tmp_path):
    good = b"good"
    bad = b"bad"
    manifest = build_source_manifest(
        good,
        source_name="CVM",
        source_url="https://dados.cvm.gov.br/file.zip",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError):
        RawEvidenceVault(tmp_path).store(bad, manifest)


def test_raw_evidence_vault_detects_tampering_on_read(tmp_path):
    payload = b"canonical"
    manifest = build_source_manifest(
        payload,
        source_name="BCB",
        source_url="https://api.bcb.gov.br/data",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    vault = RawEvidenceVault(tmp_path)
    receipt = vault.store(payload, manifest)
    receipt.payload_path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        vault.read_payload(receipt.object_sha256)


def test_raw_evidence_vault_rejects_receipt_path_content_conflict(tmp_path):
    payload = b"canonical"
    manifest = build_source_manifest(
        payload,
        source_name="CVM",
        source_url="https://dados.cvm.gov.br/data",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
    )
    vault = RawEvidenceVault(tmp_path)
    receipt = vault.store(payload, manifest)
    receipt.receipt_path.write_text("different\n", encoding="utf-8")

    with pytest.raises(RawEvidenceConflictError):
        vault.store(payload, manifest)

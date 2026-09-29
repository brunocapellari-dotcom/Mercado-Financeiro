from hashlib import sha256
import json

import pytest

from mercado_financeiro.security import (
    SupplyChainEvidence,
    assert_deployable_supply_chain,
    load_supply_chain_evidence,
)


def test_supply_chain_evidence_binds_provenance_to_sbom(tmp_path):
    sbom = b'{"bomFormat":"CycloneDX","components":[{"name":"x"}]}'
    sbom_path = tmp_path / "sbom.json"
    sbom_path.write_bytes(sbom)
    provenance = {
        "source_commit_sha": "a" * 40,
        "sbom_sha256": sha256(sbom).hexdigest(),
    }
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    evidence = load_supply_chain_evidence(
        sbom_path=sbom_path,
        provenance_path=provenance_path,
        signature_verified=False,
    )
    assert evidence.commit_sha == "a" * 40
    with pytest.raises(RuntimeError, match="verified Sigstore/cosign"):
        assert_deployable_supply_chain(evidence)


def test_supply_chain_evidence_detects_sbom_tampering(tmp_path):
    sbom_path = tmp_path / "sbom.json"
    sbom_path.write_bytes(b"tampered")
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(
        json.dumps({"source_commit_sha": "b" * 40, "sbom_sha256": "0" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="does not match"):
        load_supply_chain_evidence(
            sbom_path=sbom_path,
            provenance_path=provenance_path,
            signature_verified=True,
        )


def test_deployable_supply_chain_requires_valid_digests():
    with pytest.raises(ValueError):
        SupplyChainEvidence(
            commit_sha="short",
            sbom_sha256="a" * 64,
            provenance_sha256="b" * 64,
            signature_verified=True,
        )

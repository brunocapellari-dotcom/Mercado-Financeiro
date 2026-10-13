import pandas as pd
import pytest

from mercado_financeiro.pit.identity_gate import (
    IdentityGatePolicy,
    assert_identity_gate,
    evaluate_identity_gate,
)


def _frame(statuses, volumes):
    return pd.DataFrame(
        {
            "security_id": [f"SEC{i}" for i in range(len(statuses))],
            "identity_mapping_status": statuses,
            "financial_volume": volumes,
        }
    )


def test_identity_gate_passes_high_coverage():
    frame = _frame(["resolved", "resolved", "unresolved_no_evidence"], [980.0, 15.0, 5.0])
    result = evaluate_identity_gate(
        frame,
        IdentityGatePolicy(
            min_mapped_volume_ratio=0.99,
            min_mapped_row_ratio=0.60,
            max_single_unresolved_volume_ratio=0.01,
        ),
    )
    assert result.passed
    assert result.mapped_volume_ratio == pytest.approx(0.995)


def test_identity_gate_fails_material_unresolved_or_ambiguous():
    frame = _frame(["resolved", "ambiguous_source_conflict", "unresolved_no_evidence"], [900.0, 50.0, 50.0])
    result = evaluate_identity_gate(frame)
    assert not result.passed
    assert result.ambiguous_volume_ratio == pytest.approx(0.05)
    assert "mapped_volume_ratio" in " ".join(result.reasons)
    with pytest.raises(RuntimeError):
        assert_identity_gate(frame)


def test_identity_gate_rejects_bad_volume():
    frame = _frame(["resolved"], [-1.0])
    with pytest.raises(ValueError):
        evaluate_identity_gate(frame)

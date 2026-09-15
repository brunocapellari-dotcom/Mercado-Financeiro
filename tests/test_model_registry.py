from datetime import datetime, timezone

import pytest

from mercado_financeiro.models import ModelManifest, ModelRegistry, ModelStage


def _manifest() -> ModelManifest:
    return ModelManifest(
        model_name="b3-equity-alpha",
        version="2026.09.15.1",
        artifact_sha256="a" * 64,
        code_commit_sha="abcdef1234567890",
        dataset_manifest_sha256="b" * 64,
        feature_schema_sha256="c" * 64,
        training_start=datetime(2011, 1, 1, tzinfo=timezone.utc),
        training_end=datetime(2024, 12, 31, tzinfo=timezone.utc),
        as_of_cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        metrics=(("oos_sharpe", 1.1), ("max_drawdown", -0.12)),
    )


def test_model_versions_are_immutable_and_aliases_point_to_versions():
    registry = ModelRegistry()
    first = registry.register(_manifest())
    assert len(first.manifest_sha256) == 64
    assert not registry.durable
    with pytest.raises(ValueError, match="immutable"):
        registry.register(_manifest())

    registry.set_alias("b3-equity-alpha", "candidate", "2026.09.15.1")
    assert registry.resolve_alias("b3-equity-alpha", "candidate").manifest.version == "2026.09.15.1"


def test_model_promotion_cannot_skip_or_bypass_gates():
    registry = ModelRegistry()
    registry.register(_manifest())

    with pytest.raises(RuntimeError, match="cannot skip"):
        registry.promote(
            "b3-equity-alpha",
            "2026.09.15.1",
            ModelStage.SHADOW,
            gates={},
        )

    with pytest.raises(RuntimeError, match="required gates"):
        registry.promote(
            "b3-equity-alpha",
            "2026.09.15.1",
            ModelStage.VALIDATED,
            gates={"backtest": True, "walk_forward": False},
        )

    validated = registry.promote(
        "b3-equity-alpha",
        "2026.09.15.1",
        ModelStage.VALIDATED,
        gates={"backtest": True, "walk_forward": True},
    )
    assert validated.stage is ModelStage.VALIDATED

    paper = registry.promote(
        "b3-equity-alpha",
        "2026.09.15.1",
        ModelStage.PAPER,
        gates={"backtest": True, "walk_forward": True, "risk_validation": True},
    )
    assert paper.stage is ModelStage.PAPER

    shadow = registry.promote(
        "b3-equity-alpha",
        "2026.09.15.1",
        ModelStage.SHADOW,
        gates={
            "backtest": True,
            "walk_forward": True,
            "paper": True,
            "risk_validation": True,
        },
    )
    assert shadow.stage is ModelStage.SHADOW

    with pytest.raises(RuntimeError, match="live model promotion blocked"):
        registry.promote(
            "b3-equity-alpha",
            "2026.09.15.1",
            ModelStage.LIVE,
            gates={"backtest": True, "walk_forward": True},
        )

    live = registry.promote(
        "b3-equity-alpha",
        "2026.09.15.1",
        ModelStage.LIVE,
        gates={
            "backtest": True,
            "walk_forward": True,
            "paper": True,
            "shadow": True,
            "reconciliation": True,
            "security_test": True,
            "risk_validation": True,
        },
    )
    assert live.stage is ModelStage.LIVE

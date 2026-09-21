from decimal import Decimal

from mercado_financeiro.benchmarks import EngineParitySnapshot, compare_engine_snapshots


_DIGEST = "a" * 64


def _snapshot(engine: str, **overrides):
    values = {
        "engine": engine,
        "event_stream_sha256": _DIGEST,
        "positions": {"PETR4": Decimal("100")},
        "cash": Decimal("1000.00"),
        "realized_pnl": Decimal("10.00"),
        "cumulative_fees": Decimal("1.00"),
        "executions": 3,
        "risk_rejections": 1,
    }
    values.update(overrides)
    return EngineParitySnapshot(**values)


def test_engine_parity_passes_within_explicit_monetary_tolerance():
    result = compare_engine_snapshots(
        _snapshot("mf"),
        _snapshot("candidate", cash=Decimal("1000.005")),
        monetary_tolerance=Decimal("0.01"),
    )
    assert result.passed


def test_engine_parity_exposes_each_material_divergence():
    result = compare_engine_snapshots(
        _snapshot("mf"),
        _snapshot(
            "nautilus",
            positions={"PETR4": Decimal("99")},
            realized_pnl=Decimal("11"),
            executions=2,
        ),
    )
    assert not result.passed
    assert "position:PETR4" in result.mismatches
    assert "realized_pnl" in result.mismatches
    assert "executions" in result.mismatches

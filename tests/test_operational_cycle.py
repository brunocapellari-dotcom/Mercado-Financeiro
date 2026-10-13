from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_operational_cycle_paper_smoke_is_deterministic_and_live_disabled(tmp_path: Path):
    output = tmp_path / "evidence.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_operational_cycle.py",
            "--mode",
            "paper-smoke",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["live_trading_enabled"] is False
    assert payload["paper_smoke"]["ok"] is True
    assert payload["paper_smoke"]["market_data_mode"] == "synthetic_smoke_only"
    assert payload["paper_smoke"]["proves_current_market_data"] is False
    assert len(payload["paper_smoke"]["digest_sha256"]) == 64


def _load_operational_module():
    import importlib.util

    path = Path("scripts/run_operational_cycle.py")
    spec = importlib.util.spec_from_file_location("operational_cycle_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _market_preflight(*, quote_age_seconds: float = 600.0):
    return {
        "ok": True,
        "ticker": "PETR4",
        "price": "30",
        "received_timestamp": "2026-10-13T14:00:00+00:00",
        "quote_age_seconds": quote_age_seconds,
        "configured_max_quote_age_seconds": 2400.0,
        "synthetic_bid": "29.97",
        "synthetic_ask": "30.03",
        "volume": 1000000,
    }


def test_paper_market_cycle_executes_only_simulated_order_during_market_window():
    module = _load_operational_module()
    result = module._paper_market_cycle(_market_preflight())
    assert result["ok"] is True
    assert result["state"] == "executed"
    assert result["ticker"] == "PETR4"
    assert result["live_trading_enabled"] is False
    assert len(result["digest_sha256"]) == 64


def test_paper_market_cycle_skips_stale_delayed_quote_without_failing_job():
    module = _load_operational_module()
    result = module._paper_market_cycle(_market_preflight(quote_age_seconds=7200.0))
    assert result == {
        "ok": False,
        "state": "blocked",
        "reason": "delayed_quote_too_old_for_paper",
        "quote_age_seconds": "7200.0",
        "max_quote_age_seconds": "2400.0",
    }

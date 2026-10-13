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


def test_operational_cycle_preflight_fails_closed_without_authorized_price_url(tmp_path: Path):
    output = tmp_path / "preflight.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_operational_cycle.py",
            "--mode",
            "preflight",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
        env={},
    )
    assert completed.returncode == 3
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["operational_preflight_ready"] is False
    assert payload["authorized_price_preflight"]["state"] == "blocked"
    assert payload["authorized_price_preflight"]["reason"] == "authorized_price_report_url_missing"

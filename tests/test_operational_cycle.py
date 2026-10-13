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

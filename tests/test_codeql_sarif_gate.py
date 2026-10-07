from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _write_sarif(path: Path, *, severity: str, level: str = "warning") -> None:
    payload = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeQL",
                        "rules": [
                            {
                                "id": "py/test",
                                "properties": {"security-severity": severity},
                            }
                        ],
                    }
                },
                "results": [{"ruleId": "py/test", "level": level}],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/gate_codeql_sarif.py", str(path), "--threshold", "7.0"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_codeql_sarif_gate_blocks_high_security_finding(tmp_path: Path):
    _write_sarif(tmp_path / "python.sarif", severity="8.5")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert '"passed": false' in result.stdout


def test_codeql_sarif_gate_allows_below_threshold_finding(tmp_path: Path):
    _write_sarif(tmp_path / "python.sarif", severity="6.5")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert '"passed": true' in result.stdout


def test_codeql_sarif_gate_fails_closed_when_evidence_is_missing(tmp_path: Path):
    result = _run(tmp_path)
    assert result.returncode == 2
    assert '"passed": false' in result.stdout

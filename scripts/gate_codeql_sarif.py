from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _severity(rule: dict[str, Any], result: dict[str, Any]) -> float | None:
    for candidate in (
        result.get("properties", {}).get("security-severity"),
        rule.get("properties", {}).get("security-severity"),
    ):
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def evaluate_sarif(path: str | Path, *, threshold: float = 7.0) -> dict[str, object]:
    if threshold < 0:
        raise ValueError("threshold cannot be negative")
    root = Path(path)
    files = (root,) if root.is_file() else tuple(sorted(root.rglob("*.sarif")))
    if not files:
        raise ValueError(f"no SARIF files found under {root}")

    blocking: list[dict[str, object]] = []
    total = 0
    for sarif_file in files:
        payload = json.loads(sarif_file.read_text(encoding="utf-8"))
        for run in payload.get("runs", []):
            rules = {
                str(rule.get("id")): rule
                for rule in run.get("tool", {}).get("driver", {}).get("rules", [])
                if rule.get("id") is not None
            }
            for result in run.get("results", []):
                total += 1
                rule_id = str(result.get("ruleId", "unknown"))
                severity = _severity(rules.get(rule_id, {}), result)
                level = str(result.get("level", "warning")).lower()
                should_block = (
                    severity is not None and severity >= threshold
                ) or (severity is None and level == "error")
                if should_block:
                    blocking.append(
                        {
                            "rule_id": rule_id,
                            "severity": severity,
                            "level": level,
                            "file": sarif_file.name,
                        }
                    )

    return {
        "sarif_files": len(files),
        "results": total,
        "threshold": threshold,
        "blocking": blocking,
        "passed": not blocking,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed on high/critical CodeQL SARIF findings."
    )
    parser.add_argument("path")
    parser.add_argument("--threshold", type=float, default=7.0)
    args = parser.parse_args()
    try:
        report = evaluate_sarif(args.path, threshold=args.threshold)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {"passed": False, "error": str(exc)}
        print("CODEQL_SARIF_GATE " + json.dumps(report, sort_keys=True))
        return 2
    print("CODEQL_SARIF_GATE " + json.dumps(report, sort_keys=True))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

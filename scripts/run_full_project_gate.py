from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from mercado_financeiro.architecture.runner_independent_gate import (
    build_gate_plan,
    execute_gate_plan,
    gate_passed,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Mercado Financeiro whole-project gates without depending on "
            "GitHub-hosted runners."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic", "sources", "full"),
        default="full",
        help="full = deterministic checks plus every official-source audit",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop after the first failing command instead of collecting every failure",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    plan = build_gate_plan(args.mode, sys.executable)
    results = execute_gate_plan(plan, repository_root=root, fail_fast=args.fail_fast)
    passed = gate_passed(results)

    print(
        "WHOLE_PROJECT_GATE_SUMMARY "
        + json.dumps(
            {
                "mode": args.mode,
                "python": sys.version.split()[0],
                "commands_planned": len(plan),
                "commands_executed": len(results),
                "failed": [result.name for result in results if result.returncode != 0],
                "passed": passed and len(results) == len(plan),
            },
            sort_keys=True,
        )
    )
    return 0 if passed and len(results) == len(plan) else 1


if __name__ == "__main__":
    raise SystemExit(main())

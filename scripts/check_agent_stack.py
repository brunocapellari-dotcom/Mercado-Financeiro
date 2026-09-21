from __future__ import annotations

import json
from pathlib import Path

from mercado_financeiro.agents import load_pydantic_harness_registry


def main() -> int:
    registry = load_pydantic_harness_registry()
    cases_path = Path(__file__).resolve().parents[1] / "evals" / "research_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("canonical research regression corpus must be a non-empty list")
    required = {"name", "input", "category"}
    names: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise RuntimeError(f"research case {index} must be an object")
        missing = required - set(case)
        if missing:
            raise RuntimeError(f"research case {index} missing: {sorted(missing)}")
        name = str(case["name"]).strip()
        if not name:
            raise RuntimeError(f"research case {index} has blank name")
        if name in names:
            raise RuntimeError(f"duplicate research case name: {name}")
        names.add(name)
        if not str(case["input"]).strip() or not str(case["category"]).strip():
            raise RuntimeError(f"research case {name} has blank input/category")

    from evals.pydantic.build_dataset import build_research_dataset

    dataset = build_research_dataset()
    if len(dataset.cases) != len(cases):
        raise RuntimeError("Pydantic Evals dataset does not cover canonical corpus")

    print(
        "AGENT_STACK_OK "
        + json.dumps(
            {
                "harness_version": registry.version,
                "regression_cases": len(cases),
                "capabilities": [
                    "Planning",
                    "SubAgents",
                    "Memory",
                    "SpendLimits",
                    "TrajectoryJudge",
                    "DynamicWorkflow",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

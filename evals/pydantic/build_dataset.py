from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_evals import Case, Dataset


_CASES = Path(__file__).resolve().parents[1] / "research_cases.json"


def build_research_dataset() -> Dataset[str, dict[str, Any], Any]:
    """Build Pydantic Evals cases from the same canonical regression corpus as Promptfoo."""

    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    return Dataset(
        name="mercado_financeiro_research_agents",
        cases=[
            Case(
                name=case["name"],
                inputs=case["input"],
                metadata={"category": case["category"]},
            )
            for case in cases
        ],
    )

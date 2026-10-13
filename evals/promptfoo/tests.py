from __future__ import annotations

import json
from pathlib import Path


_CASES = Path(__file__).resolve().parents[1] / "research_cases.json"


def generate_tests(config=None):
    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    return [
        {
            "description": case["name"],
            "vars": {
                "input": case["input"],
                "category": case["category"],
            },
        }
        for case in cases
    ]

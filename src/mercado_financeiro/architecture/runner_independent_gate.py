from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable


@dataclass(frozen=True)
class GateCommand:
    name: str
    argv: tuple[str, ...]
    network_required: bool = False


@dataclass(frozen=True)
class GateCommandResult:
    name: str
    returncode: int
    elapsed_seconds: float
    network_required: bool


def deterministic_gate_plan(
    python_executable: str = sys.executable,
) -> tuple[GateCommand, ...]:
    py = python_executable
    return (
        GateCommand(
            "compileall",
            (py, "-m", "compileall", "-q", "src", "scripts", "tests", "evals"),
        ),
        GateCommand("repository-security-scan", (py, "scripts/security_scan.py")),
        GateCommand(
            "ruff-high-signal",
            (py, "-m", "ruff", "check", "src", "scripts", "tests", "evals"),
        ),
        GateCommand(
            "mypy-core",
            (py, "-m", "mypy", "src/mercado_financeiro"),
        ),
        GateCommand(
            "pytest-complete-seed-a",
            (
                py,
                "-m",
                "pytest",
                "--randomly-seed=20260921",
                "--timeout=120",
                "--cov=mercado_financeiro",
                "--cov-branch",
                "--cov-report=term-missing",
            ),
        ),
        GateCommand(
            "pytest-complete-seed-b",
            (
                py,
                "-m",
                "pytest",
                "--randomly-seed=8675309",
                "--timeout=120",
            ),
        ),
        GateCommand("agent-stack-compatibility", (py, "scripts/check_agent_stack.py")),
        GateCommand("bandit-source", (py, "-m", "bandit", "-r", "src", "-ll")),
        GateCommand("dependency-audit", (py, "-m", "pip_audit")),
    )


def official_source_gate_plan(
    python_executable: str = sys.executable,
) -> tuple[GateCommand, ...]:
    py = python_executable
    scripts = (
        ("historical-identity-2011-2026", "scripts/audit_identity_2011_2026.py"),
        ("share-history-2011-2026", "scripts/audit_share_history_2011_2026.py"),
        ("b3-company-events", "scripts/audit_b3_company_events_live.py"),
        ("fca-schema-history", "scripts/audit_fca_schema.py"),
        ("fca-negotiation-codes", "scripts/audit_fca_invalid_tickers.py"),
        ("b3-cotahist-2011", "scripts/audit_cotahist_live.py"),
        ("b3-emissor-identity", "scripts/audit_b3_emissor_identity.py"),
        ("identity-2011-base", "scripts/audit_identity_2011_live.py"),
        ("identity-2011-emissor", "scripts/audit_identity_2011_with_emissor.py"),
        ("identity-2011-exact-isin", "scripts/audit_identity_2011_exact_isin.py"),
        ("cvm-pit-history", "scripts/audit_cvm_pit_history.py"),
        ("cvm-fund-daily", "scripts/audit_cvm_fund_daily.py"),
        ("cvm-fund-holdings", "scripts/audit_cvm_fund_holdings.py"),
        ("bvbg028-history", "scripts/audit_bvbg028_history.py"),
        ("official-macro-sources", "scripts/audit_official_macro_sources.py"),
    )
    return tuple(
        GateCommand(name, (py, script), network_required=True) for name, script in scripts
    )


def build_gate_plan(
    mode: str,
    python_executable: str = sys.executable,
) -> tuple[GateCommand, ...]:
    if mode == "deterministic":
        return deterministic_gate_plan(python_executable)
    if mode == "sources":
        return official_source_gate_plan(python_executable)
    if mode == "full":
        return deterministic_gate_plan(python_executable) + official_source_gate_plan(
            python_executable
        )
    raise ValueError("mode must be one of: deterministic, sources, full")


def execute_gate_plan(
    commands: Iterable[GateCommand],
    *,
    repository_root: Path,
    fail_fast: bool = False,
) -> tuple[GateCommandResult, ...]:
    results: list[GateCommandResult] = []
    for command in commands:
        started = time.monotonic()
        print(f"GATE_START name={command.name}", flush=True)
        completed = subprocess.run(
            command.argv,
            cwd=repository_root,
            check=False,
        )
        elapsed = time.monotonic() - started
        result = GateCommandResult(
            name=command.name,
            returncode=int(completed.returncode),
            elapsed_seconds=elapsed,
            network_required=command.network_required,
        )
        results.append(result)
        print(
            "GATE_RESULT "
            + json.dumps(
                {
                    **asdict(result),
                    "status": "pass" if result.returncode == 0 else "fail",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if fail_fast and result.returncode != 0:
            break
    return tuple(results)


def gate_passed(results: Iterable[GateCommandResult]) -> bool:
    materialized = tuple(results)
    return bool(materialized) and all(result.returncode == 0 for result in materialized)

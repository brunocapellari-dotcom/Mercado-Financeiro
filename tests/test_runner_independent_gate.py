from pathlib import Path

import pytest

from mercado_financeiro.architecture.runner_independent_gate import (
    GateCommand,
    GateCommandResult,
    build_gate_plan,
    deterministic_gate_plan,
    execute_gate_plan,
    gate_passed,
    official_source_gate_plan,
)


def test_gate_plan_preserves_whole_project_boundaries():
    deterministic = deterministic_gate_plan("python-test")
    sources = official_source_gate_plan("python-test")
    full = build_gate_plan("full", "python-test")

    assert len(deterministic) == 9
    assert len(sources) == 15
    assert full == deterministic + sources
    assert all(command.argv[0] == "python-test" for command in full)
    assert not any(command.network_required for command in deterministic)
    assert all(command.network_required for command in sources)

    names = {command.name for command in full}
    assert "ruff-high-signal" in names
    assert "mypy-core" in names
    assert "pytest-complete-seed-a" in names
    assert "pytest-complete-seed-b" in names
    assert "agent-stack-compatibility" in names
    assert "dependency-audit" in names
    assert "historical-identity-2011-2026" in names
    assert "cvm-pit-history" in names
    assert "cvm-fund-daily" in names
    assert "cvm-fund-holdings" in names
    assert "official-macro-sources" in names


def test_gate_plan_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        build_gate_plan("partial")


def test_execute_gate_plan_collects_failures_without_skipping_later_checks(monkeypatch, tmp_path):
    returncodes = iter((0, 7, 0))
    calls = []

    class Completed:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(argv, cwd, check):
        calls.append((tuple(argv), Path(cwd), check))
        return Completed(next(returncodes))

    monkeypatch.setattr(
        "mercado_financeiro.architecture.runner_independent_gate.subprocess.run",
        fake_run,
    )

    commands = (
        GateCommand("one", ("python", "one.py")),
        GateCommand("two", ("python", "two.py")),
        GateCommand("three", ("python", "three.py")),
    )
    results = execute_gate_plan(commands, repository_root=tmp_path)

    assert [result.returncode for result in results] == [0, 7, 0]
    assert len(calls) == 3
    assert not gate_passed(results)


def test_gate_passed_requires_non_empty_all_green_result_set():
    assert not gate_passed(())
    assert gate_passed((GateCommandResult("ok", 0, 0.1, False),))
    assert not gate_passed(
        (
            GateCommandResult("ok", 0, 0.1, False),
            GateCommandResult("bad", 1, 0.2, True),
        )
    )

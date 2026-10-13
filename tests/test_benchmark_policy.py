import pytest

from mercado_financeiro.benchmarks.policy import (
    TOOL_POLICY,
    assert_external_tool_has_no_financial_authority,
    assert_tool_capability,
)


def test_external_benchmarks_never_hold_financial_authority():
    for tool in ("vectorbt", "nautilus", "lean", "skfolio", "qlib"):
        assert_external_tool_has_no_financial_authority(tool)
        assert not TOOL_POLICY[tool].real_capital_allowed


def test_vectorbt_is_research_backtest_only():
    assert_tool_capability("vectorbt", "backtest")
    with pytest.raises(PermissionError):
        assert_tool_capability("vectorbt", "execution")


def test_nautilus_rc_is_not_live_authority():
    assert TOOL_POLICY["nautilus"].current_line == "2.0.0rc5"
    assert not TOOL_POLICY["nautilus"].real_capital_allowed

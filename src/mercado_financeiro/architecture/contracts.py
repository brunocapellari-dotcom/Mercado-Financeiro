from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class PipelineStage(str, Enum):
    DATA = "data"
    INTELLIGENCE = "intelligence"
    FORECAST = "forecast"
    SIGNAL = "signal"
    RISK = "risk"
    EXECUTION = "execution"


PIPELINE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage.DATA,
    PipelineStage.INTELLIGENCE,
    PipelineStage.FORECAST,
    PipelineStage.SIGNAL,
    PipelineStage.RISK,
    PipelineStage.EXECUTION,
)


class AuditDomain(str, Enum):
    MARKET_DATA = "market_data"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    MACRO = "macro"
    B3 = "b3"
    CVM = "cvm"
    BCB = "bcb"
    ANBIMA = "anbima"
    NEFIN = "nefin"
    BACKTESTS = "backtests"
    VINTAGES = "vintages"
    BROKER = "broker"
    RISK = "risk"
    EXECUTION = "execution"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"
    LOGS = "logs"
    RECONCILIATION = "reconciliation"


class AIRole(str, Enum):
    MARKET_CHIEF = "market_chief_ai"
    REAL_TIME_MARKET = "real_time_market_ai"
    NEWS = "news_ai"
    MACRO = "macro_ai"
    FUNDAMENTAL = "fundamental_ai"
    TECHNICAL = "technical_ai"
    MICROSTRUCTURE = "microstructure_ai"
    QUANT_RESEARCH = "quant_research_ai"
    FORECAST = "forecast_ai"
    BULL = "bull_ai"
    BEAR = "bear_ai"
    PORTFOLIO = "portfolio_ai"
    RISK_AUDITOR = "risk_auditor_ai"
    EXECUTION_MONITOR = "execution_monitor_ai"


class DeploymentStage(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    WALK_FORWARD = "walk_forward"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


REQUIRED_LIVE_GATES: tuple[str, ...] = (
    "backtest",
    "walk_forward",
    "paper",
    "shadow",
    "reconciliation",
    "security_test",
    "risk_validation",
)


@dataclass(frozen=True)
class GateResult:
    approved: bool
    missing: tuple[str, ...]
    failed: tuple[str, ...]


def evaluate_live_promotion(gates: Mapping[str, bool | None]) -> GateResult:
    """Fail closed unless every mandatory live gate is explicitly True."""

    missing = tuple(name for name in REQUIRED_LIVE_GATES if name not in gates or gates[name] is None)
    failed = tuple(name for name in REQUIRED_LIVE_GATES if gates.get(name) is False)
    return GateResult(approved=not missing and not failed, missing=missing, failed=failed)


def assert_pipeline_transition(current: PipelineStage, target: PipelineStage) -> None:
    """Prevent architectural bypasses between canonical pipeline stages."""

    current_index = PIPELINE_ORDER.index(current)
    target_index = PIPELINE_ORDER.index(target)
    if target_index != current_index + 1:
        raise ValueError(f"invalid pipeline transition: {current.value} -> {target.value}")

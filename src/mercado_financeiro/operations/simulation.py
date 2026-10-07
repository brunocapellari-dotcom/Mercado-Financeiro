from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable, Mapping

from mercado_financeiro.accounting import MarkToMarketSnapshot, PortfolioAccountingLedger
from mercado_financeiro.execution import (
    BrokerageCostSchedule,
    DeterministicBrokerageModel,
    DeterministicExecutionEngine,
    ExecutionResult,
    MarketExecutionState,
)
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskContext

from .simulated import SimulatedBrokerAdapter


class SimulationMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"


@dataclass(frozen=True)
class SimulationEvent:
    order: OrderIntent
    market: MarketExecutionState
    marks: Mapping[str, Decimal]
    pnl_today: Decimal = Decimal("0")
    market_data_age_seconds: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.order.instrument.strip().upper() == "":
            raise ValueError("order instrument is required")
        if self.market_data_age_seconds < 0:
            raise ValueError("market_data_age_seconds cannot be negative")


@dataclass(frozen=True)
class SimulationStep:
    timestamp: datetime
    execution: ExecutionResult
    mark_to_market: MarkToMarketSnapshot


@dataclass(frozen=True)
class SimulationReport:
    mode: SimulationMode
    started_at: datetime
    ended_at: datetime
    steps: tuple[SimulationStep, ...]
    final: MarkToMarketSnapshot
    digest_sha256: str


class DeterministicSimulationSession:
    """One execution model shared by backtest, paper and shadow.

    LIVE is intentionally not a valid mode. RiskContext is derived from the
    accounting ledger and supplied market state.
    """

    def __init__(
        self,
        *,
        mode: SimulationMode,
        risk_engine: DeterministicRiskEngine,
        brokerage_schedule: BrokerageCostSchedule,
        initial_cash: Decimal,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self._mode = mode
        self._ledger = PortfolioAccountingLedger(initial_cash=initial_cash)
        self._broker = SimulatedBrokerAdapter(
            brokerage_model=DeterministicBrokerageModel(brokerage_schedule),
            ledger=self._ledger,
        )
        self._execution = DeterministicExecutionEngine(
            risk_engine=risk_engine,
            broker=self._broker,
        )
        self._peak_equity = initial_cash

    @property
    def ledger(self) -> PortfolioAccountingLedger:
        return self._ledger

    def run(self, events: Iterable[SimulationEvent]) -> SimulationReport:
        materialized = tuple(events)
        if not materialized:
            raise ValueError("simulation requires at least one event")
        timestamps = [event.market.timestamp for event in materialized]
        if any(right < left for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("simulation events must be chronological")

        steps: list[SimulationStep] = []
        last_marks: dict[str, Decimal] = {}
        for event in materialized:
            instrument = event.order.instrument.strip().upper()
            last_marks.update(
                {str(k).strip().upper(): Decimal(v) for k, v in event.marks.items()}
            )
            midpoint = (event.market.bid + event.market.ask) / Decimal("2")
            last_marks.setdefault(instrument, midpoint)

            before = self._ledger.mark_to_market(last_marks)
            self._peak_equity = max(self._peak_equity, before.equity)
            position = self._ledger.snapshot().positions.get(instrument)
            current_position = position.quantity if position is not None else Decimal("0")
            context = RiskContext(
                current_position=current_position,
                equity=before.equity,
                peak_equity=self._peak_equity,
                pnl_today=event.pnl_today,
                adv_notional=event.market.adv_notional,
                market_data_age_seconds=event.market_data_age_seconds,
                now=event.market.timestamp,
            )
            self._broker.set_market(instrument, event.market)
            execution = self._execution.execute(event.order, context)
            after = self._ledger.mark_to_market(last_marks)
            self._peak_equity = max(self._peak_equity, after.equity)
            steps.append(
                SimulationStep(
                    timestamp=event.market.timestamp,
                    execution=execution,
                    mark_to_market=after,
                )
            )

        final = steps[-1].mark_to_market
        canonical = json.dumps(
            {
                "mode": self._mode.value,
                "steps": [
                    {
                        "timestamp": step.timestamp.isoformat(),
                        "status": step.execution.status,
                        "accepted": step.execution.accepted,
                        "client_order_id": step.execution.client_order_id,
                        "equity": str(step.mark_to_market.equity),
                        "fees": str(step.mark_to_market.cumulative_fees),
                    }
                    for step in steps
                ],
                "final_equity": str(final.equity),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return SimulationReport(
            mode=self._mode,
            started_at=timestamps[0],
            ended_at=timestamps[-1],
            steps=tuple(steps),
            final=final,
            digest_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
        )

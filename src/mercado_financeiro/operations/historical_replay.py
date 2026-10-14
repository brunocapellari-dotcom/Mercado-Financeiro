"""Point-in-time paper/shadow replay over official B3 COTAHIST bars.

This module turns normalized COTAHIST regular-share quotes into a deterministic
paper/shadow cycle executed by :class:`DeterministicSimulationSession`. It never
reaches a broker: orders only flow through the deterministic risk engine and the
simulated brokerage model.

Point-in-time rules (see ``docs/point_in_time_policy.md``):

* each daily bar carries ``reference_date`` (session close of ``trade_date``) and a
  conservative ``available_from`` (next calendar day, before the next open);
* every decision filters bars with :func:`mercado_financeiro.data.historical.asof`
  at an explicit cutoff, so only information available by the cutoff is visible;
* execution happens strictly after the cutoff, on the next session in the tape, at
  that session's opening price. The opening price is the simulated market state at
  execution time and is never an input of the decision;
* bars are *not* adjusted for corporate actions. Candidates with an implausible
  daily move inside the lookback window are excluded and reported, never silently
  repaired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import ROUND_DOWN, Decimal
from hashlib import sha256
import json
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from mercado_financeiro.data.historical import VintageMode, asof
from mercado_financeiro.execution import BrokerageCostSchedule, MarketExecutionState
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskLimits

from .simulation import DeterministicSimulationSession, SimulationEvent, SimulationMode

B3_TIMEZONE = "America/Sao_Paulo"
SESSION_CLOSE_LOCAL = time(18, 0)
CONSERVATIVE_AVAILABILITY_LOCAL = time(8, 0)
EXECUTION_LOCAL = time(10, 15)

_REQUIRED_BAR_COLUMNS = {
    "trade_date",
    "ticker",
    "security_id",
    "open_quote",
    "close_price",
    "quotation_factor",
    "financial_volume",
    "quantity",
}


def _local_to_utc(day: pd.Timestamp, clock: time, tz: ZoneInfo) -> pd.Timestamp:
    local = datetime.combine(day.date(), clock, tzinfo=tz)
    return pd.Timestamp(local.astimezone(timezone.utc))


def build_cotahist_pit_bars(
    regular_share_quotes: pd.DataFrame,
    *,
    source_sha256: str,
    retrieved_at: datetime,
    timezone_name: str = B3_TIMEZONE,
) -> pd.DataFrame:
    """Attach PIT availability metadata to normalized COTAHIST share quotes.

    ``available_from`` is the next calendar day at 08:00 local time, i.e. after
    B3 publishes the daily historical quotation file and before the next open.
    Rows whose ``available_from`` is later than ``retrieved_at`` are rejected,
    because a file cannot contain information that did not exist at collection.
    """

    missing = _REQUIRED_BAR_COLUMNS - set(regular_share_quotes.columns)
    if missing:
        raise ValueError(f"COTAHIST quotes missing columns: {sorted(missing)}")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if len(source_sha256) != 64:
        raise ValueError("source_sha256 must be a sha256 hex digest")

    tz = ZoneInfo(timezone_name)
    frame = regular_share_quotes.loc[:, sorted(_REQUIRED_BAR_COLUMNS)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if frame["trade_date"].dt.tz is not None:
        raise ValueError("trade_date must be a naive exchange-local calendar date")
    frame["open_price"] = frame["open_quote"].astype(float) / frame["quotation_factor"].astype(float)
    frame["close_price"] = frame["close_price"].astype(float)
    frame["financial_volume"] = frame["financial_volume"].astype(float)
    if (frame[["open_price", "close_price"]] <= 0).any().any():
        bad = frame.loc[(frame[["open_price", "close_price"]] <= 0).any(axis=1)]
        frame = frame.drop(index=bad.index)
    days = frame["trade_date"].drop_duplicates()
    reference = {day: _local_to_utc(day, SESSION_CLOSE_LOCAL, tz) for day in days}
    available = {
        day: _local_to_utc(day + pd.Timedelta(days=1), CONSERVATIVE_AVAILABILITY_LOCAL, tz)
        for day in days
    }
    frame["reference_date"] = frame["trade_date"].map(reference)
    frame["available_from"] = frame["trade_date"].map(available)
    retrieved = pd.Timestamp(retrieved_at).tz_convert("UTC")
    if (frame["available_from"] > retrieved).any():
        raise ValueError("COTAHIST bar available_from is after the file retrieval time")
    frame["collected_at"] = retrieved
    frame["source"] = "B3_COTAHIST"
    frame["source_sha256"] = source_sha256
    frame["vintage_mode"] = VintageMode.PUBLICATION_GATED.value
    frame["evidence_class"] = "observado"
    frame["availability_rule"] = "inferido:trade_date+1d_08:00_local"
    return frame.sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)


@dataclass(frozen=True)
class ReplayConfig:
    lookback_sessions: int = 5
    liquid_universe_size: int = 10
    target_notional: Decimal = Decimal("10000")
    lot_size: int = 100
    initial_cash: Decimal = Decimal("100000")
    synthetic_spread_bps: Decimal = Decimal("20")
    max_abs_daily_return: float = 0.5
    mode: SimulationMode = SimulationMode.PAPER

    def __post_init__(self) -> None:
        if self.lookback_sessions < 1:
            raise ValueError("lookback_sessions must be >= 1")
        if self.liquid_universe_size < 1:
            raise ValueError("liquid_universe_size must be >= 1")
        if self.target_notional <= 0 or self.initial_cash <= 0:
            raise ValueError("target_notional and initial_cash must be positive")
        if self.lot_size < 1:
            raise ValueError("lot_size must be >= 1")
        if self.mode is SimulationMode.BACKTEST:
            raise ValueError("historical replay runs only as PAPER or SHADOW")


@dataclass(frozen=True)
class ReplayDecision:
    decision_date: pd.Timestamp
    cutoff: pd.Timestamp
    max_available_from_used: pd.Timestamp
    max_trade_date_used: pd.Timestamp
    execution_date: pd.Timestamp | None
    execution_timestamp: pd.Timestamp | None
    target: str | None
    target_momentum: float | None
    universe: tuple[str, ...]
    excluded_unadjusted: tuple[str, ...]
    orders: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReplayResult:
    mode: SimulationMode
    decisions: tuple[ReplayDecision, ...]
    leakage_violations: tuple[str, ...]
    final_cash: Decimal
    final_equity: Decimal
    cumulative_fees: Decimal
    realized_pnl: Decimal
    positions: dict[str, Decimal]
    accepted_orders: int
    rejected_orders: int
    digest_sha256: str


def _decide(
    visible: pd.DataFrame,
    config: ReplayConfig,
) -> tuple[str | None, float | None, tuple[str, ...], tuple[str, ...], Decimal]:
    sessions = sorted(visible["trade_date"].unique())
    window = sessions[-(config.lookback_sessions + 1) :]
    if len(window) < config.lookback_sessions + 1:
        return None, None, (), (), Decimal("0")
    recent = visible.loc[visible["trade_date"].isin(window)]
    complete = recent.groupby("ticker")["trade_date"].nunique()
    complete_tickers = complete.loc[complete.eq(len(window))].index
    recent = recent.loc[recent["ticker"].isin(complete_tickers)]
    if recent.empty:
        return None, None, (), (), Decimal("0")
    liquidity = (
        recent.groupby("ticker")["financial_volume"].mean().sort_values(ascending=False, kind="stable")
    )
    # Deterministic tie-break: volume desc, then ticker asc.
    liquidity = liquidity.reset_index().sort_values(
        ["financial_volume", "ticker"], ascending=[False, True], kind="stable"
    )
    universe = tuple(liquidity["ticker"].head(config.liquid_universe_size))
    closes = (
        recent.loc[recent["ticker"].isin(universe)]
        .pivot(index="trade_date", columns="ticker", values="close_price")
        .sort_index()
    )
    daily = closes.pct_change().iloc[1:]
    implausible = daily.abs().max() > config.max_abs_daily_return
    excluded = tuple(sorted(implausible.loc[implausible].index))
    momentum = (closes.iloc[-1] / closes.iloc[0] - 1.0).drop(labels=list(excluded))
    if momentum.empty:
        return None, None, universe, excluded, Decimal("0")
    ranked = momentum.reset_index()
    ranked.columns = ["ticker", "momentum"]
    ranked = ranked.sort_values(["momentum", "ticker"], ascending=[False, True], kind="stable")
    target = str(ranked.iloc[0]["ticker"])
    adv = Decimal(str(round(float(liquidity.set_index("ticker").loc[target, "financial_volume"]), 2)))
    return target, float(ranked.iloc[0]["momentum"]), universe, excluded, adv


def _round_lot(notional: Decimal, price: Decimal, lot: int) -> Decimal:
    lots = (notional / (price * lot)).to_integral_value(rounding=ROUND_DOWN)
    return lots * lot


def run_cotahist_paper_replay(
    bars: pd.DataFrame,
    config: ReplayConfig | None = None,
    *,
    timezone_name: str = B3_TIMEZONE,
) -> ReplayResult:
    """Run a deterministic momentum paper/shadow cycle with explicit PIT cutoffs."""

    config = config or ReplayConfig()
    required = {"trade_date", "ticker", "open_price", "close_price", "available_from"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"PIT bars missing columns: {sorted(missing)}")
    tz = ZoneInfo(timezone_name)
    tape = bars.sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
    sessions = sorted(tape["trade_date"].unique())
    if len(sessions) < config.lookback_sessions + 2:
        raise ValueError("not enough sessions for one decision and one execution")

    tickers = frozenset(str(t) for t in tape["ticker"].unique())
    risk = DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=config.target_notional * Decimal("2"),
            max_abs_position=Decimal("1000000"),
            allowed_instruments=tickers,
            trading_start=time(10, 0),
            trading_end=time(17, 55),
            trading_timezone=timezone_name,
            max_daily_loss=config.initial_cash,
        )
    )
    session = DeterministicSimulationSession(
        mode=config.mode,
        risk_engine=risk,
        brokerage_schedule=BrokerageCostSchedule(
            fee_bps=Decimal("2.5"),
            base_slippage_bps=Decimal("5"),
            max_adv_participation=Decimal("0.05"),
            settlement_business_days=0,
        ),
        initial_cash=config.initial_cash,
    )

    decisions: list[ReplayDecision] = []
    violations: list[str] = []
    chain = sha256(b"historical-replay-v1")
    accepted = 0
    rejected = 0
    spread = config.synthetic_spread_bps / Decimal("10000")

    for index in range(config.lookback_sessions, len(sessions) - 1):
        decision_day = pd.Timestamp(sessions[index])
        cutoff = _local_to_utc(decision_day + pd.Timedelta(days=1), time(8, 0), tz)
        visible = asof(tape, cutoff)
        max_available = pd.to_datetime(visible["available_from"], utc=True).max()
        max_trade = pd.Timestamp(visible["trade_date"].max())
        if max_available > cutoff:
            violations.append(f"{decision_day.date()}:available_from_after_cutoff")
        if max_trade != decision_day:
            violations.append(f"{decision_day.date()}:visible_tape_not_aligned_to_decision_day")

        target, momentum, universe, excluded, adv = _decide(visible, config)
        execution_day = pd.Timestamp(sessions[index + 1])
        execution_ts = _local_to_utc(execution_day, EXECUTION_LOCAL, tz)
        if execution_ts <= cutoff:
            violations.append(f"{decision_day.date()}:execution_not_after_cutoff")
        if execution_day <= max_trade:
            violations.append(f"{decision_day.date()}:execution_bar_inside_decision_window")

        exec_bars = tape.loc[tape["trade_date"].eq(execution_day)].set_index("ticker")
        positions = session.ledger.snapshot().positions
        events: list[SimulationEvent] = []
        marks = {
            str(t): Decimal(str(round(float(exec_bars.loc[t, "open_price"]), 6)))
            for t, pos in positions.items()
            if pos.quantity != 0 and t in exec_bars.index
        }

        def _market(ticker: str) -> MarketExecutionState | None:
            if ticker not in exec_bars.index:
                return None
            open_price = Decimal(str(round(float(exec_bars.loc[ticker, "open_price"]), 6)))
            return MarketExecutionState(
                timestamp=execution_ts.to_pydatetime(),
                bid=open_price * (Decimal("1") - spread / 2),
                ask=open_price * (Decimal("1") + spread / 2),
                available_quantity=Decimal(int(exec_bars.loc[ticker, "quantity"])),
                adv_notional=adv if ticker == target else Decimal(
                    str(round(float(exec_bars.loc[ticker, "financial_volume"]), 2))
                ),
            )

        sequence = 0
        skipped: list[dict[str, Any]] = []
        for held, pos in sorted(positions.items()):
            if pos.quantity == 0 or held == target or target is None:
                continue
            market = _market(held)
            if market is None:
                skipped.append({"instrument": held, "status": "skipped:no_execution_bar"})
                continue
            sequence += 1
            events.append(
                SimulationEvent(
                    order=OrderIntent(
                        instrument=held,
                        side="sell" if pos.quantity > 0 else "buy",
                        quantity=abs(pos.quantity),
                        price=market.bid,
                        signal_id=f"mom{config.lookback_sessions}:{decision_day.date()}",
                        idempotency_key=f"replay:{decision_day.date()}:{sequence}:{held}",
                        created_at=cutoff.to_pydatetime(),
                    ),
                    market=market,
                    marks=marks,
                )
            )
        if target is not None and target not in {t for t, p in positions.items() if p.quantity}:
            market = _market(target)
            if market is None:
                skipped.append({"instrument": target, "status": "skipped:no_execution_bar"})
            else:
                quantity = _round_lot(config.target_notional, market.ask, config.lot_size)
                if quantity <= 0:
                    skipped.append(
                        {"instrument": target, "status": "skipped:lot_notional_exceeds_target"}
                    )
                else:
                    sequence += 1
                    events.append(
                        SimulationEvent(
                            order=OrderIntent(
                                instrument=target,
                                side="buy",
                                quantity=quantity,
                                price=market.ask,
                                signal_id=f"mom{config.lookback_sessions}:{decision_day.date()}",
                                idempotency_key=f"replay:{decision_day.date()}:{sequence}:{target}",
                                created_at=cutoff.to_pydatetime(),
                            ),
                            market=market,
                            marks=marks,
                        )
                    )

        order_rows: list[dict[str, Any]] = list(skipped)
        if events:
            report = session.run(events)
            chain.update(report.digest_sha256.encode("ascii"))
            for event, step in zip(events, report.steps):
                accepted += int(step.execution.accepted is True)
                rejected += int(step.execution.accepted is not True)
                order_rows.append(
                    {
                        "instrument": event.order.instrument,
                        "side": event.order.side,
                        "quantity": str(event.order.quantity),
                        "limit_reference": str(event.order.price),
                        "status": step.execution.status,
                        "accepted": step.execution.accepted,
                        "reasons": list(step.execution.risk_reasons),
                    }
                )
        decisions.append(
            ReplayDecision(
                decision_date=decision_day,
                cutoff=cutoff,
                max_available_from_used=max_available,
                max_trade_date_used=max_trade,
                execution_date=execution_day,
                execution_timestamp=execution_ts,
                target=target,
                target_momentum=momentum,
                universe=universe,
                excluded_unadjusted=excluded,
                orders=tuple(order_rows),
            )
        )
        chain.update(
            json.dumps(
                {
                    "d": str(decision_day.date()),
                    "t": target,
                    "u": list(universe),
                    "x": list(excluded),
                },
                sort_keys=True,
            ).encode("utf-8")
        )

    last_day = pd.Timestamp(sessions[-1])
    last_bars = tape.loc[tape["trade_date"].eq(last_day)].set_index("ticker")
    snapshot = session.ledger.snapshot()
    final_marks = {
        str(t): Decimal(str(round(float(last_bars.loc[t, "close_price"]), 6)))
        for t, pos in snapshot.positions.items()
        if pos.quantity != 0 and t in last_bars.index
    }
    missing_marks = [
        t for t, pos in snapshot.positions.items() if pos.quantity != 0 and t not in final_marks
    ]
    if missing_marks:
        violations.append(f"final_marks_missing:{','.join(sorted(missing_marks))}")
        for t in missing_marks:
            final_marks[t] = snapshot.positions[t].average_price
    mtm = session.ledger.mark_to_market(final_marks)
    chain.update(str(mtm.equity).encode("ascii"))
    return ReplayResult(
        mode=config.mode,
        decisions=tuple(decisions),
        leakage_violations=tuple(violations),
        final_cash=snapshot.cash,
        final_equity=mtm.equity,
        cumulative_fees=snapshot.cumulative_fees,
        realized_pnl=snapshot.realized_pnl,
        positions={t: p.quantity for t, p in snapshot.positions.items() if p.quantity != 0},
        accepted_orders=accepted,
        rejected_orders=rejected,
        digest_sha256=chain.hexdigest(),
    )


def replay_summary(result: ReplayResult) -> dict[str, Any]:
    return {
        "mode": result.mode.value,
        "decisions": len(result.decisions),
        "first_decision": str(result.decisions[0].decision_date.date()) if result.decisions else None,
        "last_decision": str(result.decisions[-1].decision_date.date()) if result.decisions else None,
        "accepted_orders": result.accepted_orders,
        "rejected_orders": result.rejected_orders,
        "leakage_violations": list(result.leakage_violations),
        "final_cash": str(result.final_cash),
        "final_equity": str(result.final_equity),
        "cumulative_fees": str(result.cumulative_fees),
        "realized_pnl": str(result.realized_pnl),
        "positions": {k: str(v) for k, v in sorted(result.positions.items())},
        "digest_sha256": result.digest_sha256,
        "targets": [
            {
                "decision_date": str(d.decision_date.date()),
                "execution_date": str(d.execution_date.date()) if d.execution_date is not None else None,
                "target": d.target,
                "momentum": d.target_momentum,
                "excluded_unadjusted": list(d.excluded_unadjusted),
                "orders": list(d.orders),
            }
            for d in result.decisions
        ],
    }


__all__ = [
    "ReplayConfig",
    "ReplayDecision",
    "ReplayResult",
    "build_cotahist_pit_bars",
    "replay_summary",
    "run_cotahist_paper_replay",
]

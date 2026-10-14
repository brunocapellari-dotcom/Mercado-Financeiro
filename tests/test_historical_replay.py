"""Artificial-fixture tests for the PIT COTAHIST paper/shadow replay (no real data)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from mercado_financeiro.operations.historical_replay import (
    ReplayConfig,
    build_cotahist_pit_bars,
    run_cotahist_paper_replay,
)
from mercado_financeiro.operations.simulation import SimulationMode

SHA = "a" * 64
RETRIEVED = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
DAYS = pd.bdate_range("2026-09-01", periods=10)
DRIFT = {"AAA3": 0.01, "BBB4": 0.02, "CCC3": -0.01, "DDD3": 0.0}


def _quotes(drift: dict[str, float] | None = None) -> pd.DataFrame:
    drift = drift or DRIFT
    rows = []
    for ticker, slope in drift.items():
        price = 20.0
        for day in DAYS:
            open_price = price
            price = price * (1.0 + slope)
            rows.append(
                {
                    "trade_date": day,
                    "ticker": ticker,
                    "security_id": f"ISIN:BR{ticker}000000",
                    "open_quote": round(open_price, 2),
                    "close_price": round(price, 2),
                    "quotation_factor": 1,
                    "financial_volume": 5_000_000.0 + 1_000.0 * len(ticker),
                    "quantity": 200_000,
                }
            )
    return pd.DataFrame(rows)


def _bars(drift: dict[str, float] | None = None) -> pd.DataFrame:
    return build_cotahist_pit_bars(_quotes(drift), source_sha256=SHA, retrieved_at=RETRIEVED)


def test_pit_bars_are_available_only_after_the_session() -> None:
    bars = _bars()
    assert (bars["available_from"] > bars["reference_date"]).all()
    assert bars["vintage_mode"].eq("publication_gated").all()
    assert bars["source_sha256"].eq(SHA).all()
    first = bars.loc[bars["trade_date"].eq(DAYS[0])].iloc[0]
    # 2026-09-01 bar becomes eligible 2026-09-02 08:00 America/Sao_Paulo (11:00 UTC).
    assert first["available_from"] == pd.Timestamp("2026-09-02 11:00", tz="UTC")


def test_pit_bars_reject_files_claiming_future_information() -> None:
    with pytest.raises(ValueError, match="after the file retrieval time"):
        build_cotahist_pit_bars(
            _quotes(),
            source_sha256=SHA,
            retrieved_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )


def test_replay_is_deterministic_and_leakage_free() -> None:
    config = ReplayConfig(lookback_sessions=3, liquid_universe_size=4)
    first = run_cotahist_paper_replay(_bars(), config)
    second = run_cotahist_paper_replay(_bars(), config)
    assert first.digest_sha256 == second.digest_sha256
    assert first.leakage_violations == ()
    assert first.accepted_orders >= 1
    for decision in first.decisions:
        assert decision.max_available_from_used <= decision.cutoff
        assert decision.max_trade_date_used == decision.decision_date
        assert decision.execution_timestamp is not None
        assert decision.execution_timestamp > decision.cutoff
        assert decision.execution_date > decision.max_trade_date_used
    # Strongest positive drift wins the momentum ranking.
    assert first.decisions[0].target == "BBB4"


def test_future_bars_cannot_change_past_decisions() -> None:
    """Perturbing only the last sessions must not alter decisions made before them."""

    config = ReplayConfig(lookback_sessions=3, liquid_universe_size=4)
    base = run_cotahist_paper_replay(_bars(), config)
    perturbed_quotes = _quotes()
    tail = perturbed_quotes["trade_date"].isin(DAYS[-2:]) & perturbed_quotes["ticker"].eq("CCC3")
    perturbed_quotes.loc[tail, "close_price"] *= 1.4
    perturbed = run_cotahist_paper_replay(
        build_cotahist_pit_bars(perturbed_quotes, source_sha256=SHA, retrieved_at=RETRIEVED),
        config,
    )
    cutoff_day = DAYS[-2]
    before = [d for d in base.decisions if d.decision_date < cutoff_day]
    after = [d for d in perturbed.decisions if d.decision_date < cutoff_day]
    assert before
    assert [(d.decision_date, d.target, d.universe) for d in before] == [
        (d.decision_date, d.target, d.universe) for d in after
    ]


def test_unadjusted_corporate_action_jumps_are_excluded_not_repaired() -> None:
    quotes = _quotes()
    split = quotes["ticker"].eq("BBB4") & quotes["trade_date"].ge(DAYS[4])
    quotes.loc[split, ["open_quote", "close_price"]] /= 4  # 4:1 split, unadjusted
    bars = build_cotahist_pit_bars(quotes, source_sha256=SHA, retrieved_at=RETRIEVED)
    result = run_cotahist_paper_replay(bars, ReplayConfig(lookback_sessions=3, liquid_universe_size=4))
    flagged = [d for d in result.decisions if "BBB4" in d.excluded_unadjusted]
    assert flagged
    assert all(d.target != "BBB4" for d in flagged)


def test_replay_never_runs_as_backtest_or_live() -> None:
    with pytest.raises(ValueError, match="PAPER or SHADOW"):
        ReplayConfig(mode=SimulationMode.BACKTEST)
    assert not hasattr(SimulationMode, "LIVE")


def test_shadow_mode_matches_paper_economics() -> None:
    paper = run_cotahist_paper_replay(_bars(), ReplayConfig(lookback_sessions=3))
    shadow = run_cotahist_paper_replay(
        _bars(), ReplayConfig(lookback_sessions=3, mode=SimulationMode.SHADOW)
    )
    assert paper.final_equity == shadow.final_equity
    assert paper.final_equity > Decimal("0")
    assert shadow.mode is SimulationMode.SHADOW

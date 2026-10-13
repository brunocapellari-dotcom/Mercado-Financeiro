from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from mercado_financeiro.data.b3_prices import B3PriceReportSource
from mercado_financeiro.execution import BrokerageCostSchedule, MarketExecutionState
from mercado_financeiro.operations.simulation import (
    DeterministicSimulationSession,
    SimulationEvent,
    SimulationMode,
)
from mercado_financeiro.risk import DeterministicRiskEngine, OrderIntent, RiskLimits


SOURCE_AUDITS: tuple[tuple[str, str], ...] = (
    ("macro", "scripts/audit_official_macro_sources.py"),
    ("bcb_olinda", "scripts/audit_bcb_olinda_live.py"),
    ("cvm_fund_daily", "scripts/audit_cvm_fund_daily.py"),
    ("b3_company_events", "scripts/audit_b3_company_events_live.py"),
)


def _run_audit(name: str, script: str) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    completed = subprocess.run(
        [sys.executable, script],
        text=True,
        capture_output=True,
        check=False,
    )
    ended = datetime.now(timezone.utc)
    return {
        "name": name,
        "script": script,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout_tail": completed.stdout[-12000:],
        "stderr_tail": completed.stderr[-12000:],
    }


def _paper_smoke() -> dict[str, Any]:
    now = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
    risk = DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=Decimal("10000"),
            max_abs_position=Decimal("1000"),
            allowed_instruments=frozenset({"PETR4"}),
            trading_start=time(10, 0),
            trading_end=time(18, 0),
            max_daily_loss=Decimal("1000"),
        )
    )
    session = DeterministicSimulationSession(
        mode=SimulationMode.PAPER,
        risk_engine=risk,
        brokerage_schedule=BrokerageCostSchedule(
            fee_bps=Decimal("2"),
            base_slippage_bps=Decimal("5"),
            max_adv_participation=Decimal("0.05"),
            settlement_business_days=0,
        ),
        initial_cash=Decimal("100000"),
    )
    report = session.run(
        [
            SimulationEvent(
                order=OrderIntent(
                    instrument="PETR4",
                    side="buy",
                    quantity=Decimal("100"),
                    price=Decimal("30"),
                    signal_id="operational-smoke",
                    idempotency_key="operational-smoke-1",
                    created_at=now,
                ),
                market=MarketExecutionState(
                    timestamp=now,
                    bid=Decimal("29.99"),
                    ask=Decimal("30.01"),
                    available_quantity=Decimal("10000"),
                    adv_notional=Decimal("10000000"),
                ),
                marks={"PETR4": Decimal("30")},
                market_data_age_seconds=Decimal("1"),
            )
        ]
    )
    step = report.steps[0]
    return {
        "ok": bool(step.execution.accepted),
        "mode": report.mode.value,
        "market_data_mode": "synthetic_smoke_only",
        "digest_sha256": report.digest_sha256,
        "execution_status": step.execution.status,
        "final_equity": str(report.final.equity),
        "cumulative_fees": str(report.final.cumulative_fees),
        "proves_current_market_data": False,
    }


def _authorized_price_preflight() -> dict[str, Any]:
    url = os.environ.get("MF_PRICE_REPORT_URL", "").strip()
    dataset = os.environ.get("MF_PRICE_REPORT_DATASET", "BVBG.186.01").strip().upper()
    ticker = os.environ.get("MF_PAPER_TICKER", "PETR4").strip().upper()

    if not url:
        return {
            "ok": False,
            "state": "blocked",
            "reason": "authorized_price_report_url_missing",
            "required_secret": "MF_PRICE_REPORT_URL",
            "dataset": dataset,
            "ticker": ticker,
        }

    source = B3PriceReportSource()
    historical = source.fetch_url(url, dataset=dataset)
    frame = historical.frame
    selected = frame.loc[frame["ticker"].astype(str).str.upper().eq(ticker)].copy()
    if selected.empty:
        return {
            "ok": False,
            "state": "blocked",
            "reason": "configured_ticker_missing_from_authorized_price_report",
            "dataset": dataset,
            "ticker": ticker,
            "source_sha256": historical.sha256,
        }

    selected = selected.sort_values("reference_date", kind="stable")
    row = selected.iloc[-1]
    best_bid = row.get("best_bid")
    best_ask = row.get("best_ask")
    close_price = row.get("close_price")
    executable_quote = (
        best_bid is not None
        and best_ask is not None
        and not bool(getattr(best_bid, "__class__", object).__name__ == "NAType")
        and not bool(getattr(best_ask, "__class__", object).__name__ == "NAType")
    )
    return {
        "ok": True,
        "state": "ready",
        "dataset": dataset,
        "ticker": ticker,
        "reference_date": str(row["reference_date"]),
        "available_from": str(row["available_from"]),
        "source_sha256": historical.sha256,
        "raw_receipt_present": bool(str(row.get("raw_receipt_id", "")).strip()),
        "best_bid": None if best_bid is None else str(best_bid),
        "best_ask": None if best_ask is None else str(best_ask),
        "close_price": None if close_price is None else str(close_price),
        "executable_quote_present": executable_quote,
        "note": (
            "The URL must come from an authorized/licensed source path. "
            "This runner never discovers or scrapes B3 download pages."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("source-audit", "paper-smoke", "preflight", "full"),
        default="full",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "mode": args.mode,
        "started_at": started.isoformat(),
        "live_trading_enabled": False,
    }

    if args.mode in {"source-audit", "full"}:
        payload["source_audits"] = [
            _run_audit(name, script) for name, script in SOURCE_AUDITS
        ]

    if args.mode in {"paper-smoke", "full"}:
        payload["paper_smoke"] = _paper_smoke()

    if args.mode in {"preflight", "full"}:
        payload["authorized_price_preflight"] = _authorized_price_preflight()

    source_ok = all(item["ok"] for item in payload.get("source_audits", []))
    paper_ok = bool(payload.get("paper_smoke", {"ok": True})["ok"])
    preflight = payload.get("authorized_price_preflight")
    price_ok = True if preflight is None else bool(preflight["ok"])

    payload["source_audits_ok"] = source_ok
    payload["paper_smoke_ok"] = paper_ok
    payload["authorized_price_ready"] = price_ok
    payload["operational_preflight_ready"] = source_ok and paper_ok and price_ok
    payload["ended_at"] = datetime.now(timezone.utc).isoformat()

    encoded = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    print(encoded, end="")
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")

    return 0 if payload["operational_preflight_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from zoneinfo import ZoneInfo

from mercado_financeiro.data import BrapiMarketDataProvider
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


def _market_data_preflight() -> dict[str, Any]:
    ticker = os.environ.get("MF_PAPER_TICKER", "PETR4").strip().upper()
    api_key = os.environ.get("BRAPI_API_KEY", "").strip() or None
    provider = BrapiMarketDataProvider(api_key=api_key)
    provider.connect()
    event = provider.snapshot([ticker])[0]
    provider.disconnect()

    payload = dict(event.payload)
    quote_age_seconds = max(
        0.0,
        (event.received_timestamp - event.exchange_timestamp).total_seconds(),
    )
    max_quote_age_seconds = float(
        os.environ.get("MF_PAPER_MAX_QUOTE_AGE_SECONDS", "2400")
    )
    price = Decimal(str(payload["price"]))
    spread_bps = Decimal(os.environ.get("MF_PAPER_SYNTHETIC_SPREAD_BPS", "20"))
    spread = spread_bps / Decimal("10000")
    bid = price * (Decimal("1") - spread / Decimal("2"))
    ask = price * (Decimal("1") + spread / Decimal("2"))

    return {
        "ok": True,
        "state": "ready",
        "provider": event.provider,
        "ticker": ticker,
        "price": str(price),
        "exchange_timestamp": event.exchange_timestamp.isoformat(),
        "received_timestamp": event.received_timestamp.isoformat(),
        "quote_age_seconds": quote_age_seconds,
        "configured_max_quote_age_seconds": max_quote_age_seconds,
        "fresh_for_paper": quote_age_seconds <= max_quote_age_seconds,
        "source_sha256": payload["source_sha256"],
        "market_data_class": payload["market_data_class"],
        "volume": payload.get("volume"),
        "api_key_present": api_key is not None,
        "synthetic_bid": str(bid),
        "synthetic_ask": str(ask),
        "synthetic_spread_bps": str(spread_bps),
        "execution_feed": False,
        "note": (
            "BRAPI is delayed polling market data. Bid/ask are conservative synthetic "
            "PAPER marks derived from the delayed last price; they are never presented "
            "as exchange executable quotes and are forbidden for LIVE."
        ),
    }




def _paper_market_cycle(preflight: dict[str, Any]) -> dict[str, Any]:
    if not bool(preflight.get("ok")):
        return {"ok": False, "state": "blocked", "reason": "market_data_preflight_failed"}

    quote_age = Decimal(str(preflight["quote_age_seconds"]))
    max_age = Decimal(str(preflight["configured_max_quote_age_seconds"]))
    now = datetime.fromisoformat(str(preflight["received_timestamp"]))
    if quote_age > max_age:
        return {
            "ok": False,
            "state": "blocked",
            "reason": "delayed_quote_too_old_for_paper",
            "quote_age_seconds": str(quote_age),
            "max_quote_age_seconds": str(max_age),
        }

    local = now.astimezone(ZoneInfo("America/Sao_Paulo"))
    if local.weekday() >= 5 or not (time(10, 0) <= local.time().replace(tzinfo=None) <= time(18, 0)):
        return {
            "ok": False,
            "state": "blocked",
            "reason": "outside_paper_market_window",
            "local_time": local.isoformat(),
        }

    ticker = str(preflight["ticker"])
    price = Decimal(str(preflight["price"]))
    bid = Decimal(str(preflight["synthetic_bid"]))
    ask = Decimal(str(preflight["synthetic_ask"]))
    risk = DeterministicRiskEngine(
        RiskLimits(
            max_order_notional=Decimal("1000"),
            max_abs_position=Decimal("10"),
            allowed_instruments=frozenset({ticker}),
            trading_start=time(10, 0),
            trading_end=time(18, 0),
            max_daily_loss=Decimal("100"),
            max_market_data_age_seconds=max_age,
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
    volume = Decimal(str(preflight.get("volume") or "1000000"))
    adv_notional = max(price * volume, Decimal("1000000"))
    report = session.run(
        [
            SimulationEvent(
                order=OrderIntent(
                    instrument=ticker,
                    side="buy",
                    quantity=Decimal("1"),
                    price=price,
                    signal_id="brapi-paper-health",
                    idempotency_key=f"brapi-paper-{now.strftime('%Y%m%dT%H%M')}-{ticker}",
                    created_at=now,
                ),
                market=MarketExecutionState(
                    timestamp=now,
                    bid=bid,
                    ask=ask,
                    available_quantity=max(volume, Decimal("1")),
                    adv_notional=adv_notional,
                ),
                marks={ticker: price},
                market_data_age_seconds=quote_age,
            )
        ]
    )
    step = report.steps[0]
    return {
        "ok": bool(step.execution.accepted),
        "state": "executed" if step.execution.accepted else "rejected",
        "ticker": ticker,
        "execution_status": step.execution.status,
        "digest_sha256": report.digest_sha256,
        "final_equity": str(report.final.equity),
        "market_data_class": "brapi_delayed_with_synthetic_paper_spread",
        "live_trading_enabled": False,
    }


def _persist_cloud_evidence(encoded: str, payload: dict[str, Any]) -> str | None:
    bucket_name = os.environ.get("MF_EVIDENCE_BUCKET", "").strip()
    if not bucket_name:
        return None

    from google.cloud import storage

    prefix = os.environ.get(
        "MF_EVIDENCE_PREFIX",
        "operational/mercado-financeiro",
    ).strip("/")
    ended_at = str(payload["ended_at"]).replace(":", "").replace("-", "")
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    object_name = f"{prefix}/{ended_at}-{digest}.json"

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_string(
        encoded,
        content_type="application/json",
        if_generation_match=0,
    )
    return f"gs://{bucket_name}/{object_name}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("source-audit", "paper-smoke", "preflight", "paper", "full"),
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

    if args.mode in {"preflight", "paper", "full"}:
        payload["market_data_preflight"] = _market_data_preflight()

    if args.mode in {"paper", "full"}:
        payload["paper_market_cycle"] = _paper_market_cycle(
            payload["market_data_preflight"]
        )

    source_ok = all(item["ok"] for item in payload.get("source_audits", []))
    paper_ok = bool(payload.get("paper_smoke", {"ok": True})["ok"])
    preflight = payload.get("market_data_preflight")
    price_ok = True if preflight is None else bool(preflight["ok"])
    paper_market = payload.get("paper_market_cycle")
    paper_market_ok = True if paper_market is None else bool(paper_market["ok"])

    payload["source_audits_ok"] = source_ok
    payload["paper_smoke_ok"] = paper_ok
    payload["market_data_ready"] = price_ok
    payload["paper_market_ok"] = paper_market_ok
    payload["operational_preflight_ready"] = source_ok and paper_ok and price_ok and paper_market_ok
    payload["ended_at"] = datetime.now(timezone.utc).isoformat()

    encoded = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")

    cloud_uri = _persist_cloud_evidence(encoded, payload)
    if cloud_uri is not None:
        payload["cloud_evidence_uri"] = cloud_uri
        encoded = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"

    print(encoded, end="")
    return 0 if payload["operational_preflight_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

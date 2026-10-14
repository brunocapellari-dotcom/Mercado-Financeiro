"""Download one official B3 COTAHIST file and run a PIT paper/shadow replay.

Raw files are written only to an external data directory (``--data-dir`` or
``MF_DATA_DIR``) that must live outside the repository. No broker, credential or
real order path exists: execution is simulated by DeterministicSimulationSession.

Example::

    MF_DATA_DIR=/srv/mf-data python scripts/run_historical_paper_replay.py --month 092026
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

from mercado_financeiro.b3.cotahist import read_cotahist, select_regular_share_quotes
from mercado_financeiro.operations.historical_replay import (
    ReplayConfig,
    build_cotahist_pit_bars,
    replay_summary,
    run_cotahist_paper_replay,
)
from mercado_financeiro.operations.simulation import SimulationMode
from mercado_financeiro.security import DownloadPolicy, RetryPolicy, download_https_with_retry

MONTHLY_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_M{month}.ZIP"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _external_dir(raw: str | None) -> Path:
    if not raw:
        raise SystemExit("--data-dir or MF_DATA_DIR is required (external storage only)")
    path = Path(raw).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise SystemExit("data directory must be outside the Git repository")
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="MMYYYY, e.g. 092026")
    parser.add_argument("--data-dir", default=os.environ.get("MF_DATA_DIR"))
    parser.add_argument("--mode", choices=["paper", "shadow"], default="paper")
    parser.add_argument("--lookback", type=int, default=5)
    parser.add_argument("--universe", type=int, default=10)
    parser.add_argument("--reuse", action="store_true", help="reuse an already downloaded file")
    parser.add_argument("--out", help="write the JSON report to this external path")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"(0[1-9]|1[0-2])\d{4}", args.month):
        raise SystemExit("--month must be MMYYYY")
    data_dir = _external_dir(args.data_dir)
    target = data_dir / f"COTAHIST_M{args.month}.ZIP"
    url = MONTHLY_URL.format(month=args.month)
    receipt_path = target.with_suffix(".receipt.json")

    if args.reuse and target.exists() and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload = target.read_bytes()
        if sha256(payload).hexdigest() != receipt["sha256"]:
            raise SystemExit("cached COTAHIST file does not match its receipt digest")
        retrieved_at = datetime.fromisoformat(receipt["retrieved_at"])
    else:
        retrieved_at = datetime.now(timezone.utc)
        payload = download_https_with_retry(
            url,
            DownloadPolicy(max_bytes=200_000_000, timeout_seconds=240.0),
            retry_policy=RetryPolicy(attempts=4, initial_delay_seconds=2.0, max_delay_seconds=20.0),
            headers={"Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8"},
        )
        target.write_bytes(payload)
        receipt = {
            "source": "B3_COTAHIST",
            "url": url,
            "retrieved_at": retrieved_at.isoformat(),
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
            "classification": "UNTRUSTED_EXTERNAL_until_parsed",
        }
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")

    raw = read_cotahist(target)
    shares, audit = select_regular_share_quotes(raw)
    bars = build_cotahist_pit_bars(
        shares, source_sha256=receipt["sha256"], retrieved_at=retrieved_at
    )
    config = ReplayConfig(
        lookback_sessions=args.lookback,
        liquid_universe_size=args.universe,
        mode=SimulationMode(args.mode),
    )
    first = run_cotahist_paper_replay(bars, config)
    second = run_cotahist_paper_replay(bars, config)
    report = {
        "receipt": receipt,
        "ingestion_audit": {
            "rows": audit.rows,
            "share_rows": audit.share_rows,
            "unique_dates": audit.unique_dates,
            "unique_tickers": audit.unique_tickers,
            "unique_isins": audit.unique_isins,
            "missing_isin_rows": audit.missing_isin_rows,
            "first_trade_date": str(bars["trade_date"].min().date()),
            "last_trade_date": str(bars["trade_date"].max().date()),
            "max_available_from": bars["available_from"].max().isoformat(),
            "vintage_mode": bars["vintage_mode"].iloc[0],
        },
        "replay": replay_summary(first),
        "deterministic_rerun_digest_match": first.digest_sha256 == second.digest_sha256,
        "real_money": False,
        "broker_boundary": "none (simulated brokerage only)",
    }
    text = json.dumps(report, sort_keys=True, indent=2, default=str)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        if out == REPO_ROOT or REPO_ROOT in out.parents:
            raise SystemExit("--out must be outside the Git repository")
        out.write_text(text, encoding="utf-8")
    print(text)
    ok = (
        not first.leakage_violations
        and report["deterministic_rerun_digest_match"]
        and first.final_equity > Decimal("0")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

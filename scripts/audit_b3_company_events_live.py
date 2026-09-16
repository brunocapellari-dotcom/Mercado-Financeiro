from __future__ import annotations

from datetime import datetime, timezone
import json

from mercado_financeiro.b3 import B3CompanyEventsSource


COMPANIES = ("PETR", "VALE", "ITUB", "BBAS")


def main() -> None:
    source = B3CompanyEventsSource()
    records: list[dict[str, object]] = []
    total_rows = 0
    rows_with_isin = 0
    for company in COMPANIES:
        events, audit = source.fetch(
            company,
            retrieved_at=datetime.now(timezone.utc),
        )
        record = {
            "issuing_company": company,
            "rows": audit.rows,
            "cash_rows": audit.cash_rows,
            "stock_rows": audit.stock_rows,
            "subscription_rows": audit.subscription_rows,
            "rows_with_isin": audit.rows_with_isin,
            "sha256": audit.source_sha256,
            "labels": sorted(events["event_type_raw"].dropna().astype(str).unique().tolist()),
        }
        records.append(record)
        total_rows += audit.rows
        rows_with_isin += audit.rows_with_isin
        print("B3_COMPANY_EVENTS_SOURCE " + json.dumps(record, sort_keys=True))

    summary = {
        "companies": list(COMPANIES),
        "total_rows": total_rows,
        "rows_with_isin": rows_with_isin,
        "all_passed": total_rows > 0 and rows_with_isin > 0,
        "note": (
            "B3 current snapshots are historical-reconciliation evidence. Historical "
            "publication-time availability remains gated on contemporaneous evidence."
        ),
    }
    print("B3_COMPANY_EVENTS_GATE " + json.dumps(summary, sort_keys=True))
    if not summary["all_passed"]:
        raise SystemExit("B3 company-event source returned no usable historical event identity")


if __name__ == "__main__":
    main()

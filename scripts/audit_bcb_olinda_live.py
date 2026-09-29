from __future__ import annotations

from datetime import datetime, timezone
import json

from mercado_financeiro.data import (
    BCBMarketExpectationsSource,
    BCBPtaxSource,
    FocusEndpoint,
)


def main() -> int:
    retrieved = datetime.now(timezone.utc)

    ptax = BCBPtaxSource().fetch(
        "2026-09-25",
        "2026-09-25",
        retrieved_at=retrieved,
    )
    if ptax.frame.empty:
        raise RuntimeError("official BCB PTAX audit returned no rows")
    if not {"buy", "sell", "reference_date", "available_from"}.issubset(ptax.frame.columns):
        raise RuntimeError("official BCB PTAX schema is missing canonical fields")
    if (ptax.frame["available_from"] != ptax.frame["reference_date"]).any():
        raise RuntimeError("PTAX publication timestamps are not preserved")

    focus = BCBMarketExpectationsSource().fetch(
        FocusEndpoint.ANNUAL,
        start="2026-09-01",
        end="2026-09-25",
        indicator="IPCA",
        top=500,
        retrieved_at=retrieved,
    )
    if focus.frame.empty:
        raise RuntimeError("official BCB Focus audit returned no rows")
    if not {"series_id", "forecast_reference", "median", "available_from"}.issubset(
        focus.frame.columns
    ):
        raise RuntimeError("official BCB Focus schema is missing canonical fields")
    if not focus.frame["available_from"].eq(retrieved).all():
        raise RuntimeError("Focus historical availability must remain conservative")

    print(
        "BCB_OLINDA_AUDIT "
        + json.dumps(
            {
                "ptax_rows": len(ptax.frame),
                "focus_rows": len(focus.frame),
                "ptax_sha256": ptax.sha256,
                "focus_sha256": focus.sha256,
                "retrieved_at": retrieved.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

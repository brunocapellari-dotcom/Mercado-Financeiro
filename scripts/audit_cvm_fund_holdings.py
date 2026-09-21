from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from mercado_financeiro.data import CVMFundHoldingsSource


def main() -> int:
    now = datetime.now(timezone.utc)
    first_this_month = now.date().replace(day=1)
    previous_month = first_this_month - timedelta(days=1)

    dataset = CVMFundHoldingsSource().fetch_coded_asset_aggregate(
        previous_month.year,
        previous_month.month,
        retrieved_at=now,
    )
    frame = dataset.frame
    if frame.empty:
        raise RuntimeError("CVM CDA coded-asset aggregate is empty")
    if frame["asset_code"].nunique() < 10:
        raise RuntimeError("CVM CDA has implausibly few coded assets")
    if int(frame["fund_count"].max()) < 1:
        raise RuntimeError("CVM CDA has no disclosed fund participation")
    if frame["reference_date"].isna().any() or frame["available_from"].isna().any():
        raise RuntimeError("CVM CDA contains invalid temporal fields")
    if (frame["available_from"] < frame["reference_date"]).any():
        raise RuntimeError("CVM CDA availability precedes reference date")
    if frame["coverage_status"].isna().any():
        raise RuntimeError("CVM CDA coverage status missing")

    print(
        "CVM_FUND_HOLDINGS_OK "
        + json.dumps(
            {
                "rows": len(frame),
                "coded_assets": int(frame["asset_code"].nunique()),
                "max_fund_count": int(frame["fund_count"].max()),
                "first_reference": frame["reference_date"].min().isoformat(),
                "last_reference": frame["reference_date"].max().isoformat(),
                "retrieved_at": dataset.retrieved_at_utc.isoformat(),
                "sha256": dataset.sha256,
                "vintage_mode": dataset.vintage_mode.value,
                "coverage_statuses": sorted(frame["coverage_status"].astype(str).unique().tolist()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

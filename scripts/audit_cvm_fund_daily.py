from __future__ import annotations

from datetime import datetime, timezone
import json

from mercado_financeiro.data import CVMFundDailySource


def main() -> int:
    now = datetime.now(timezone.utc)
    dataset = CVMFundDailySource().fetch_month(now.year, now.month, retrieved_at=now)
    frame = dataset.frame
    if frame.empty:
        raise RuntimeError("CVM fund daily current-month dataset is empty")
    if frame["fund_id"].nunique() < 100:
        raise RuntimeError("CVM fund daily has implausibly few funds")
    if frame["reference_date"].max() > frame["available_from"].max():
        raise RuntimeError("CVM fund reference date exceeds collection availability")
    print(
        "CVM_FUND_DAILY_OK "
        + json.dumps(
            {
                "rows": len(frame),
                "funds": int(frame["fund_id"].nunique()),
                "first_reference": frame["reference_date"].min().isoformat(),
                "last_reference": frame["reference_date"].max().isoformat(),
                "retrieved_at": dataset.retrieved_at_utc.isoformat(),
                "sha256": dataset.sha256,
                "vintage_mode": dataset.vintage_mode.value,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

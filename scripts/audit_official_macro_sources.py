from __future__ import annotations

from datetime import datetime, timezone

from mercado_financeiro.data import BCBSgsSource, NEFINRiskFactorsSource
from mercado_financeiro.data.bcb_catalog import BCB_SERIES_CATALOG


def main() -> None:
    retrieved = datetime.now(timezone.utc)
    bcb = BCBSgsSource()
    for contract in BCB_SERIES_CATALOG.values():
        dataset = bcb.fetch(
            contract.sgs_code,
            start="2026-01-01",
            retrieved_at=retrieved,
            publication_lag_days=contract.publication_lag_days,
        )
        frame = dataset.frame
        print(
            "BCB_SOURCE_AUDIT "
            f"key={contract.key.value} code={contract.sgs_code} rows={len(frame)} "
            f"first={frame['reference_date'].min() if len(frame) else None} "
            f"last={frame['reference_date'].max() if len(frame) else None} "
            f"vintage_mode={dataset.vintage_mode.value} sha256={dataset.sha256}"
        )

    nefin = NEFINRiskFactorsSource().fetch(retrieved_at=retrieved)
    frame = nefin.frame
    print(
        "NEFIN_SOURCE_AUDIT "
        f"rows={len(frame)} first={frame['reference_date'].min() if len(frame) else None} "
        f"last={frame['reference_date'].max() if len(frame) else None} "
        f"columns={list(frame.columns)!r} vintage_mode={nefin.vintage_mode.value} "
        f"sha256={nefin.sha256}"
    )


if __name__ == "__main__":
    main()

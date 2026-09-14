# Execution Plan — P0 to Tournament

## Current critical path

1. Preserve immutable B3/CVM raw snapshots and manifests.
2. Rebuild Security Master 2011–2026 with temporal identity and delistings.
3. Build `shares_outstanding_pit` by security class.
4. Build `market_cap_pit` using compatible class price and PIT shares.
5. Materialize `tradable_universe_pit` without survivorship bias.
6. Reconcile corporate actions and total return.
7. Materialize `fundamentals_pit` and feature lineage.
8. Audit factor replication against NEFIN.
9. Run Tournament 2011–2026 with walk-forward/OOS, realistic costs and anti-overfitting tests.
10. Promote only approved models to shadow/paper; LIVE remains blocked.

## Hard gates

- no unresolved material identity gaps;
- no future `available_from` leakage;
- no silent exclusion of delisted/failed securities;
- no unresolved material corporate action in promoted windows;
- deterministic experiment fingerprinting;
- independent validation before promotion;
- explicit capacity, drawdown and risk-of-ruin controls.

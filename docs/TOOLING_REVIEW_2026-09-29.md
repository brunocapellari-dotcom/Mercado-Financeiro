# Tooling review — 2026-09-29

## Decisions

This review updates the external-tool policy without creating parallel sources of truth.

- **VectorBT 1.1.x** returns as an external research/backtest benchmark. Its recent
  Rust-backed work and corrected Deflated Sharpe implementation make it useful for
  independent metric/performance comparison. It has no risk, broker or live authority.
- **NautilusTrader 2.0.0rc5** remains an isolated event-driven/runtime benchmark.
  Release-candidate status keeps real capital explicitly disabled.
- **LEAN** remains the independent simple-strategy parity implementation.
- **Qlib 0.9.x** remains the ML/factor benchmark.
- **skfolio 0.20.x** remains the portfolio-optimization benchmark.
- **Internal PIT, risk, accounting and execution contracts remain canonical.**

## Newly closed implementation gaps

1. Official BCB Olinda PTAX collector with row-level publication timestamps.
2. Official aggregated Focus collector with conservative retrieval-time availability.
3. CVM DFP/ITR accounting-line normalization with exact account-code mappings only.
4. Canonical factor baseline library: value, momentum, quality, low-risk and liquidity.
5. Versioned research strategy catalogue with explicit economic hypotheses.
6. Machine-enforced external-tool authority policy.

## Reproducibility

The repository keeps upper bounds around optional validation/agent dependencies and
the full project gate remains the acceptance contract. A generated lock file is not
committed until an executor can resolve the complete dependency graph and verify it
on both supported Python lines. Fabricating a lock without resolver evidence would
reduce, not improve, reproducibility.

## Runtime benchmark rule

No external engine is promoted because its feature list looks stronger. Promotion
requires canonical event replay, accounting, fees, positions, risk rejection,
reconciliation and recovery parity against the same scenario corpus.

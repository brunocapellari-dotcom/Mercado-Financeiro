# Tooling and execution review — 2026-09-18

## Context

Mercado Financeiro remains in a private GitHub repository and currently has no
available GitHub Actions runners. This does **not** change the quality bar:
whole-project validation is still required before merge or promotion.

This review therefore has two goals:

1. remove GitHub-hosted runners as a single point of failure for validation;
2. review current open-source quantitative tooling without creating overlapping
   sources of truth.

## Runner-independent whole-project gate — ADOPT

The repository now exposes a canonical runner-independent gate through:

`python scripts/run_full_project_gate.py --mode full`

It executes the same deterministic and official-source boundaries that matter to
the final architecture instead of assuming GitHub Actions is the only executor.

Required validation policy while GitHub runners are unavailable:

- Python 3.11: run `--mode deterministic`;
- Python 3.12: run `--mode full`;
- install the complete project with test and validation extras before either run;
- do not merge merely because files compile or a subset of tests passes;
- official-source failures remain real gate failures and may not be waived by
  changing the runner surface.

GitHub Actions may call the same boundaries later, but Actions is orchestration,
not the definition of correctness.

## GitHub quantitative tooling round

### microsoft/qlib — ADOPT AS RESEARCH / ML BENCHMARK ADAPTER

Status reviewed on 2026-09-18: active, MIT licensed, with current commits in
September 2026.

Why it adds value:

- full quantitative ML pipeline;
- factor research and model experimentation;
- point-in-time database support;
- portfolio and execution research components;
- existing Ibovespa-oriented examples/data support;
- active integration with RD-Agent for automated factor/model R&D.

Boundary:

Qlib must never become the canonical B3/CVM data authority. Mercado Financeiro's
own PIT Security Master, `available_from`, corporate-action, identity, provenance
and Tournament contracts remain authoritative. Qlib is an independent research
and model benchmark fed only with PIT-valid exports.

### skfolio — PROMOTE TO FIRST PORTFOLIO-OPTIMIZER BENCHMARK

Status reviewed on 2026-09-18: active; v1.2.8 released on 2026-09-16; BSD-3-Clause.

Decision:

Promote skfolio from a generic future candidate to the **first** external
portfolio-optimization benchmark once PIT portfolio inputs are materialized.

Use it to challenge deterministic baselines for:

- mean-risk allocation;
- risk budgeting / diversification;
- cross-validation-aware portfolio selection;
- sensitivity to estimation error and constraints.

It remains behind a Mercado Financeiro optimizer protocol. No strategy may bypass
Risk Engine limits because an external optimizer produced weights.

### nautechsystems/nautilus_trader — EXECUTION RUNTIME REFERENCE, ISOLATED

Status reviewed on 2026-09-18: very active, LGPL-3.0, Rust-native production
trading engine. Current upstream Python support is 3.12–3.14.

Decision:

Do not add NautilusTrader to the Python 3.11-compatible core. Its best fit is an
isolated Python 3.12+ execution/backtest runtime behind Mercado Financeiro's
BrokerAdapter and risk boundaries.

Useful capabilities:

- deterministic event-driven simulation;
- live/backtest architectural parity;
- order-book/tick data;
- venue adapters;
- persistence/reconciliation concepts;
- advanced order semantics.

It may not replace the project Risk Engine, idempotency contract, reconciliation
gate or broker credential isolation.

### nkaz001/hftbacktest — MICROSTRUCTURE / FILL-MODEL BENCHMARK

Status reviewed: MIT licensed; Python 3.11+; most recent upstream commits observed
in December 2025.

Strengths:

- L2/L3 replay;
- feed/order latency models;
- queue-position-aware fill simulation;
- multi-asset/multi-exchange replay.

Decision:

Reference/benchmark only for intraday or order-book execution work. The initial
Mercado Financeiro mandate is days-to-weeks B3 equities/ETFs, so importing an HFT
engine into the core today would be premature. It becomes relevant when actual
LOB data and execution-impact calibration exist.

### QuantConnect/Lean — INDEPENDENT BACKTEST PARITY REFERENCE

Status reviewed on 2026-09-18: active, Apache-2.0. Current commits include fixes
for fundamental look-ahead and ticker/map-file boundary handling, directly
relevant to the biases Mercado Financeiro is designed to control.

Decision:

Use LEAN as an external parity/reference engine for selected simple strategies,
not as the canonical engine. Its separate C# runtime and data conventions make it
valuable as an independent implementation, but unsuitable as a second source of
truth for B3 PIT identity.

### OpenBB — DISCOVERY / SECONDARY ADAPTER ONLY

Status reviewed: active, AGPL-3.0.

OpenBB remains useful for source discovery and broad provider abstraction, but it
does not replace B3, CVM, BCB, ANBIMA or NEFIN. Its license and aggregator nature
also argue against embedding it into the canonical data plane without a concrete
need and legal review.

### FinRL — REJECT FOR CURRENT CORE

FinRL is useful for reinforcement-learning research, but RL adds a large search
space and overfitting surface before the project's simpler PIT/OOS baselines are
fully validated. Do not add it to the current core.

### astral-sh/uv — ADOPT LATER FOR REPRODUCIBLE ENVIRONMENTS

Upstream is very active and supports lockfiles plus managed Python versions. It is
a strong solution for quickly recreating Python 3.11/3.12 validation environments
outside GitHub Actions.

Do not claim reproducibility until a reviewed `uv.lock` is actually generated and
the whole-project gate passes from that lock. Migration from pip should therefore
be a tested replacement, not a documentation-only switch.

### nektos/act — OPTIONAL DEVELOPER CONVENIENCE, NOT A TRUST GATE

`act` can execute many GitHub Actions workflows locally and is MIT licensed.
However, container images and runner behavior are not identical to GitHub-hosted
runners. It can help reproduce workflow logic, but successful `act` execution
must not be treated as stronger evidence than the canonical runner-independent
gate.

## Architecture decisions from this round

1. GitHub remains the code authority, but GitHub Actions is no longer the only
   possible gate executor.
2. Whole-project correctness is defined by repository code and source audits,
   not by a specific CI vendor.
3. Qlib becomes the first external ML/factor research benchmark.
4. skfolio becomes the first external portfolio-optimizer benchmark.
5. NautilusTrader remains the preferred execution-runtime reference, isolated on
   Python 3.12+ rather than forcing the core off Python 3.11.
6. LEAN is retained as an independent backtest parity implementation.
7. HftBacktest is reserved for real L2/L3 microstructure work.
8. FinRL is rejected from the current core until conventional OOS baselines are
   strong enough to justify RL.
9. OpenBB stays secondary; official Brazilian sources remain canonical.
10. No new framework is allowed to bypass PIT, provenance, Tournament, Risk
    Engine, reconciliation or promotion gates.

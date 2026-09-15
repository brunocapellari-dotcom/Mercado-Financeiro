# Tooling and data review — 2026-09-15

This review is part of the final integrated architecture.  The rule is replacement or
adoption only when a tool materially improves correctness, reproducibility, scale or
security.  Popularity alone is not a reason to add a dependency, and overlapping
frameworks are rejected to avoid tool-sprawl.

## Adopted in this review

### DuckDB 1.5.x — ADOPT

Latest stable GitHub release reviewed: v1.5.5 (2026-07-22), MIT licensed.

Role in Mercado Financeiro:
- embedded analytical execution engine for the 2011+ PIT data plane;
- immutable snapshot manifests with source SHA-256 and retrieval timestamp;
- fast local analytical queries without introducing a server/database operations
  dependency;
- point-in-time query boundary filters `available_from` before selecting latest rows.

DuckDB does **not** replace raw official B3/CVM files.  The source artifacts and their
hashes remain canonical evidence.  It replaces ad-hoc repeated in-memory scans when
panels become too large for a pure pandas workflow.

### Hypothesis — ADOPT (test only)

Property-based tests now exercise no-lookahead invariants across generated publication
and observation lags.  It complements, rather than duplicates, example-based pytest
coverage.

## Retained as references, not added as overlapping core dependencies

### exchange_calendars — REFERENCE / NO CORE DEPENDENCY

The project has a BVMF implementation with historical Brazilian holiday and session
rules.  It is useful as an independent reference.  Mercado Financeiro already has an
`ObservedB3SettlementCalendar` built from official B3 sessions, which is stronger for
historical replay because it uses the sessions actually observed in canonical B3 data
and fails closed outside that coverage.  Adding a second calendar as an execution
source would create two truths.  Therefore the official observed calendar remains
canonical; exchange_calendars can be used in future parity audits, not as authority.

### vectorbt 1.1.0 — REFERENCE / NO CORE DEPENDENCY

The current release supports modern pandas/NumPy/Python and is strong for high-speed
vectorized experimentation.  It is not adopted as the canonical backtester because
Mercado Financeiro requires B3-specific PIT identity, explicit information-availability
timestamps, corporate-action evidence, deterministic costs, capacity, settlement and
promotion gates.  A generic engine would duplicate or bypass those controls.  It may
later serve as an independent numerical cross-check for simple strategies.

### skfolio 1.2.6 — REFERENCE / LATER OPTIMIZATION ADAPTER

Actively maintained, BSD-3-Clause, with strong portfolio optimization and model-
selection facilities.  It is a good candidate when the production portfolio optimizer
is introduced.  It is not added now because the current project does not yet have a
canonical optimizer to replace; adding it today would be unused dependency surface.
When adopted, it should sit behind a Mercado Financeiro portfolio-optimizer protocol
and be compared against simple deterministic baselines.

### PYield — REFERENCE / OPTIONAL FIXED-INCOME FUTURE

Useful Brazilian fixed-income tooling for DI futures, government bonds, ANBIMA and BCB
sources.  Current upstream requires Python >=3.12 and brings a separate data stack,
while Mercado Financeiro deliberately validates Python 3.11 and 3.12 and already owns
canonical BCB/ANBIMA adapters.  It is retained as a cross-validation and methodology
reference, not duplicated in core.  Revisit if the project intentionally moves the
minimum runtime to Python 3.12.

### Brasa — REFERENCE FOR B3 FILE DISCOVERY

Useful implementation evidence for historical B3 market-data acquisition and BVBG
formats.  Official B3 artifacts remain the source of truth; Brasa is not promoted to a
canonical data source.

### OpenFinData / other Brazilian aggregators — REFERENCE ONLY

Useful for API/client patterns and broad source discovery.  Aggregator output must not
replace B3, CVM, BCB, ANBIMA or NEFIN primary evidence in PIT research.

### BrazilianMarketDataCollector — REJECT

Upstream documentation itself reports that its B3 collector stopped working after B3
API changes.  It is unsuitable as a production dependency.

## Tools deliberately not introduced

Airflow, dbt, Polars, Streamlit and a separate feature-store service were not added.
The present workload does not justify five overlapping operational layers.  GitHub
Actions already provides deterministic validation orchestration; DuckDB plus immutable
PIT snapshots provides the needed analytical store; the existing feature contracts
provide feature provenance.  Add infrastructure only when a measured bottleneck or
operational requirement demands it.

## Architecture changes resulting from the review

1. Official-source HTTP resilience is centralized under one allowlisted HTTPS/retry
   boundary instead of being reimplemented in individual collectors.
2. DuckDB becomes the analytical PIT store while official raw artifacts remain
   immutable evidence.
3. Hypothesis joins pytest for generated no-lookahead invariant tests.
4. The Tournament now has one common OOS runner for transaction costs, cost stress,
   PBO, PSR/DSR and White's Reality Check; live promotion remains a separate risk gate.
5. The full-project gate now includes live CVM PIT boundary vintages in addition to
   deterministic, historical identity, B3 instrument and macro source checks.
6. Historical B3 settlement sessions remain official-observation-driven rather than
   introducing a competing third-party calendar source.

## Next tool reviews

Re-evaluate tools only at concrete boundaries: portfolio optimization (skfolio), large
parallel feature computation if DuckDB becomes a bottleneck, broker FIX/API execution,
and an external independent backtest parity engine.  Each candidate must pass license,
Python-version, security, determinism, PIT and whole-project regression gates before it
can replace an existing component.

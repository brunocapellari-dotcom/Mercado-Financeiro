# Tooling and data review — 2026-09-15

This review is part of the final integrated architecture. The rule is replacement or
adoption only when a tool materially improves correctness, reproducibility, scale or
security. Popularity alone is not a reason to add a dependency, and overlapping
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

DuckDB does **not** replace raw official B3/CVM files. The source artifacts and their
hashes remain canonical evidence. It replaces ad-hoc repeated in-memory scans when
panels become too large for a pure pandas workflow.

### Hypothesis — ADOPT (test only)

Property-based tests now exercise no-lookahead invariants across generated publication
and observation lags. It complements, rather than duplicates, example-based pytest
coverage.

## Google Cloud preparation review

### googleapis/google-cloud-python — ADOPT AS FUTURE OFFICIAL CLIENT REFERENCE

GitHub review shows that the active Google Cloud Python libraries are consolidated in
the non-archived `googleapis/google-cloud-python` monorepo. The older split
`googleapis/python-bigquery` repository is archived. Future BigQuery integration must
therefore follow the maintained monorepo/client distribution rather than pinning design
decisions to an archived split repository.

The client is **not** added to the core dependency set yet because the current PR does
not create Google Cloud resources. When cloud deployment is authorized it should be an
optional cloud dependency behind the existing data contracts, not a replacement for
local deterministic tests.

### terraform-google-modules/terraform-google-bigquery — REFERENCE FOR FUTURE IAC

The repository is active and is the preferred implementation reference for BigQuery
infrastructure-as-code. We will not vendor it blindly. Dataset, IAM, retention,
partitioning, labels, encryption and deletion protection must remain explicit in our
own reviewed Terraform configuration when deployment begins.

### dbt-labs/dbt-bigquery — DO NOT ADOPT AS NEW CORE LAYER

The standalone adapter repository is archived. More importantly, Mercado Financeiro
already owns explicit PIT transformations and tests. Introducing dbt merely because the
warehouse is BigQuery would add a second transformation truth and extra operational
surface. Revisit only if a concrete migration proves that dbt reduces complexity while
preserving all PIT and provenance contracts.

### dbt-labs/bigquery-adbc — BENCHMARK / FUTURE CONNECTIVITY CANDIDATE

This project is active and is worth benchmarking later for high-throughput BigQuery
connectivity. It is not adopted now because there is no measured connector bottleneck
and the official Google client remains the baseline implementation target.

## Retained as references, not added as overlapping core dependencies

### exchange_calendars — REFERENCE / NO CORE DEPENDENCY

The project has a BVMF implementation with historical Brazilian holiday and session
rules. It is useful as an independent reference. Mercado Financeiro already has an
`ObservedB3SettlementCalendar` built from official B3 sessions, which is stronger for
historical replay because it uses the sessions actually observed in canonical B3 data
and fails closed outside that coverage. Adding a second calendar as an execution
source would create two truths. Therefore the official observed calendar remains
canonical; exchange_calendars can be used in future parity audits, not as authority.

### vectorbt 1.1.0 — REFERENCE / NO CORE DEPENDENCY

The current release supports modern pandas/NumPy/Python and is strong for high-speed
vectorized experimentation. It is not adopted as the canonical backtester because
Mercado Financeiro requires B3-specific PIT identity, explicit information-availability
timestamps, corporate-action evidence, deterministic costs, capacity, settlement and
promotion gates. A generic engine would duplicate or bypass those controls. It may
later serve as an independent numerical cross-check for simple strategies.

### skfolio 1.2.6 — REFERENCE / LATER OPTIMIZATION ADAPTER

Actively maintained, BSD-3-Clause, with strong portfolio optimization and model-
selection facilities. It is a good candidate when the production portfolio optimizer
is introduced. It is not added now because the current project does not yet have a
canonical optimizer to replace; adding it today would be unused dependency surface.
When adopted, it should sit behind a Mercado Financeiro portfolio-optimizer protocol
and be compared against simple deterministic baselines.

### PYield — REFERENCE / OPTIONAL FIXED-INCOME FUTURE

Useful Brazilian fixed-income tooling for DI futures, government bonds, ANBIMA and BCB
sources. Current upstream requires Python >=3.12 and brings a separate data stack,
while Mercado Financeiro deliberately validates Python 3.11 and 3.12 and already owns
canonical BCB/ANBIMA adapters. It is retained as a cross-validation and methodology
reference, not duplicated in core. Revisit if the project intentionally moves the
minimum runtime to Python 3.12.

### Brasa — REFERENCE FOR B3 FILE DISCOVERY

Useful implementation evidence for historical B3 market-data acquisition and BVBG
formats. Official B3 artifacts remain the source of truth; Brasa is not promoted to a
canonical data source.

### OpenFinData / other Brazilian aggregators — REFERENCE ONLY

Useful for API/client patterns and broad source discovery. Aggregator output must not
replace B3, CVM, BCB, ANBIMA or NEFIN primary evidence in PIT research.

### BrazilianMarketDataCollector — REJECT

Upstream documentation itself reports that its B3 collector stopped working after B3
API changes. It is unsuitable as a production dependency.

## Tools deliberately not introduced

Airflow, dbt, Polars, Streamlit and a separate feature-store service were not added.
The present workload does not justify overlapping operational layers. GitHub Actions
already provides deterministic validation orchestration; DuckDB plus immutable PIT
snapshots provides the local analytical store; the existing feature contracts provide
feature provenance. Google Cloud preparation does not change this rule: BigQuery is a
future persistent/scale target, not permission to add an orchestration stack before a
measured requirement exists.

## Architecture changes resulting from the review

1. Official-source HTTP resilience is centralized under one allowlisted HTTPS/retry
   boundary instead of being reimplemented in individual collectors.
2. DuckDB becomes the local analytical PIT store while official raw artifacts remain
   immutable evidence.
3. Hypothesis joins pytest for generated no-lookahead invariant tests.
4. The Tournament has one common OOS runner for transaction costs, cost stress, PBO,
   PSR/DSR and White's Reality Check; live promotion remains a separate risk gate.
5. The full-project gate includes live CVM PIT boundary vintages in addition to
   deterministic, historical identity, B3 instrument and macro source checks.
6. Historical B3 settlement sessions remain official-observation-driven rather than
   introducing a competing third-party calendar source.
7. Google Cloud migration is explicitly dual-engine: Cloud Storage/BigQuery for the
   future persistent data plane, DuckDB retained for local deterministic parity and
   replay.
8. Replit, Claude Code and other development surfaces are subordinate to GitHub and
   cannot become independent code/data/deployment authorities.

## Next tool reviews

Re-evaluate tools only at concrete boundaries: portfolio optimization (skfolio),
high-throughput BigQuery connectivity (official client versus ADBC), large parallel
feature computation if DuckDB becomes a bottleneck, broker FIX/API execution, and an
external independent backtest parity engine. Each candidate must pass license,
Python-version, security, determinism, PIT and whole-project regression gates before it
can replace an existing component.

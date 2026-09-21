# Google Cloud readiness contract

Mercado Financeiro will migrate its persistent analytical data plane to Google Cloud only after the complete repository gate is green. No external Google Cloud resource is created by this document or by the current pull request.

## Canonical ownership

GitHub is the canonical source for code, schemas, tests, infrastructure definitions and deployment policy. Replit, Claude Code, Codex and other development environments may work only from Git branches and may not become independent sources of truth. Changes created elsewhere must return to GitHub and pass the same full-project gate before they are accepted.

Official source artifacts remain canonical evidence even after cloud migration. B3, CVM, BCB, ANBIMA and other raw payloads are never replaced by transformed warehouse tables.

## Target data plane

The intended production layout is:

1. **Cloud Storage raw evidence** — immutable raw B3/CVM/BCB/ANBIMA/NEFIN files, original bytes when licensing permits, SHA-256, source URL/identifier, retrieval timestamp, reference/publication dates, parser version and license/usage metadata.
2. **BigQuery provenance/manifest layer** — one append-only manifest row per acquired artifact and one immutable snapshot receipt per curated ingestion.
3. **BigQuery PIT curated layer** — normalized issuer, security, listing, prices, corporate actions, fundamentals, macro and factor tables with explicit `reference_date`, `available_from`, source identity and snapshot provenance.
4. **BigQuery research marts** — universe, market cap, total return, feature mart, labels and Tournament inputs generated only from PIT-valid curated tables.
5. **DuckDB local/parity layer** — retained for deterministic local research, tests, developer workflows and cloud-vs-local reconciliation. DuckDB is not discarded when BigQuery is introduced.

The cloud implementation must preserve the current invariant: filter `available_from <= asof` before any latest-row selection.

## BigQuery physical design rules

- Curated fact tables should be date-partitioned only on a field that materially reduces scan cost without changing PIT semantics. `available_from` or a dedicated ingestion/retrieval date is preferred for large append-only histories; accounting `reference_date` alone must never be treated as information availability.
- Cluster keys should start with stable entity keys used in PIT queries (`issuer_id`, `security_id`, `listing_id`) and then temporal keys when useful.
- Raw manifests and snapshot receipts are append-only. Reuse of a snapshot id with a different source hash is a hard conflict.
- Schema drift must fail closed. Schema changes require an explicit migration reviewed in Git.
- Point-in-time marts must retain provenance columns sufficient to trace a value back to source artifact, parser version and snapshot.
- No current-universe table may be backfilled into historical periods.
- No BigQuery view or scheduled query may silently substitute a later revised filing for information that was unavailable at the historical cutoff.

## Cloud security rules

- Do not store long-lived service-account JSON keys in GitHub, Replit, local repos or notebooks.
- Prefer Workload Identity Federation / short-lived credentials for CI/CD and workload execution.
- Production datasets use least-privilege service accounts separated by ingest, transform, research and read-only roles.
- Raw evidence buckets use versioning/retention controls appropriate to licensing and regulatory constraints.
- Public internet egress from production collectors is allowlisted by source contract where practical.
- Secrets remain in a managed secret store, not repository files or environment templates containing real values.
- Audit logs, failed jobs, schema changes and destructive operations must be retained and reviewable.

## Migration acceptance gates

Google Cloud cannot become canonical until all of the following are simultaneously true:

- local complete test suite green on supported Python versions;
- Bandit, CodeQL and dependency audit green;
- official-source integration gates green;
- cloud ingestion reproduces raw SHA-256/source metadata exactly;
- DuckDB and BigQuery produce identical PIT row sets for fixed historical cutoffs on a representative longitudinal sample;
- identical market-cap, total-return, feature and Tournament inputs within explicit numeric tolerances;
- zero rows with `available_from > asof` in parity tests;
- restore/rebuild test proves the warehouse can be reconstructed from canonical raw evidence plus versioned code;
- cost controls, quotas, labels and dataset retention policies are defined;
- backup/export and incident rollback procedures are tested;
- LIVE trading remains blocked independently by the trading risk gates.

## Infrastructure strategy

When deployment is authorized, infrastructure must be defined as code in this repository before creation. The preferred reference is the actively maintained `terraform-google-modules/terraform-google-bigquery` project, but we will not vendor or copy its implementation blindly. Google client libraries should follow the active `googleapis/google-cloud-python` monorepo rather than archived split repositories such as `googleapis/python-bigquery`.

`dbt-bigquery` itself is archived upstream, so dbt is not introduced as a new mandatory layer merely for BigQuery adoption. The project already owns explicit PIT transformations and tests; adding dbt would be justified only if it demonstrably reduces operational complexity without creating a second transformation truth. `dbt-labs/bigquery-adbc` is retained as an evaluation target for a future high-throughput connectivity layer, not a current dependency.

## Replit and Claude Code preparation

Replit and Claude Code can be used after the GitHub implementation is complete enough for a controlled handoff. Their required workflow is:

1. clone/checkout the GitHub branch;
2. run the complete local test and security gate before modifying code;
3. never bypass PIT, source, risk or security contracts;
4. commit changes to a Git branch;
5. return changes to GitHub for CI and review;
6. never create cloud resources, broker connections or live credentials unless an explicitly approved deployment step exists in GitHub;
7. never weaken tests or coverage thresholds merely to make a build pass.

This preserves one codebase, one data contract and one deployment authority while still allowing multiple development environments later.


## Query portability review — 2026-09-21

Ibis Framework 12 is the preferred candidate for a future query-portability adapter
because it supports both DuckDB and BigQuery behind one expression API. It is not a
replacement for `PITSnapshotStore` and is not yet a mandatory dependency.

Before adoption, representative PIT transforms must compile/run on both backends and
produce identical entity sets, temporal filtering, null semantics and numeric results
within explicit tolerances.

dlt and Dagster remain deferred. They may be adopted later only if measured against
the current collectors/gate and shown to reduce total ingestion/orchestration code
without weakening source security, raw-evidence preservation or PIT provenance.

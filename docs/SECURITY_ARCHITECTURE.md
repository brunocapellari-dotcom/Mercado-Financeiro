# Security Architecture

## Security objectives

The platform must protect source integrity, point-in-time correctness, confidential operational information, model/research integrity and execution safety independently. A successful backtest based on corrupted, revised or future-known data is treated as a security failure, not only a research error.

## Mandatory segregation

`Research != Live execution` is a hard physical/logical boundary.

Research environments may access approved research data and model artifacts. They must not have broker credentials, order-entry permissions or the ability to alter live risk limits.

Live execution uses a restricted runtime with its own service identity, network policy, secrets and audit trail. It consumes only promoted/versioned artifacts. No notebook, LLM session, prompt state or ad-hoc research process may execute inside the broker credential boundary.

LLMs never receive trading credentials. Risk Engine and Execution Engine are deterministic services and remain authoritative even when an AI agent recommends an action.

## Threat model

Primary threats are: credential leakage; malicious or compromised upstream files; ZIP/path traversal and decompression bombs; source substitution or silent upstream revision; API/DNS/host spoofing; webhook spoofing and replay; stale or gapped market data; duplicate orders; race conditions; idempotency failure; supply-chain compromise; untrusted pull-request code gaining write/secrets access; model/data poisoning; look-ahead; unauthorized live trading; broker/API compromise; reconciliation drift; and irreversible deletion/overwrite of raw or execution evidence.

## Trust boundaries

- **External sources:** untrusted until HTTPS host, response size, archive safety, schema and digest are validated.
- **Raw vault/object storage:** append-only logical layer. Revisions create new vintages; they do not overwrite evidence.
- **Normalization/PIT layer:** deterministic transforms only, with lineage back to raw digests.
- **Feature/model layer:** consumes approved PIT contracts only. No direct public-network fetches inside backtests.
- **Signal layer:** produces proposals only and has no broker authority.
- **Risk layer:** deterministic, independent veto, no LLM override.
- **Execution layer:** isolated credentials and permissions; accepts only risk-approved intents.
- **Broker boundary:** credentials, IP allowlists/MFA and broker-specific controls live only here.

## Required provenance manifest

Each external object must record at minimum:

- source URL and canonical source name;
- retrieval timestamp in UTC;
- exchange timestamp and received timestamp for live events when available;
- sequence number when supplied by the source;
- content byte size;
- SHA-256;
- source publication/reference timestamp if known;
- parser/schema version;
- upstream identifier/file name;
- parent digest(s) for derived datasets;
- run/commit identifier.

## Network and egress policy

Ingestion helpers default-deny unknown hosts and require HTTPS. Redirects are revalidated. URLs containing embedded username/password are rejected. Timeouts and maximum response sizes are mandatory.

The live execution environment must use egress allowlists restricted to required broker, market-data, secret-manager, logging and time-synchronization endpoints. IP restrictions must be enabled when supported. Research jobs do not share the live egress identity.

## Secrets and identity

- Broker/API credentials are stored only in an approved secret manager or equivalent protected runtime secret facility.
- Credentials are never committed to Git, embedded in config, logged, copied into prompts or returned by application APIs.
- Live service identities follow least privilege and are separate from Research identities.
- MFA is mandatory for human access to broker/vendor/admin surfaces when supported.
- Long-lived credentials are avoided where workload identity/short-lived tokens exist.
- Secret rotation and revocation must be tested before live promotion.

## Webhooks

Webhook signatures are verified using the vendor's documented scheme whenever available. Verification must include constant-time signature comparison, bounded timestamp age and replay protection through an event identifier/nonces. Unsigned webhooks are untrusted input and cannot directly change risk limits, positions or execution state.

## Market-data integrity

Live collectors must reconnect safely, capture exchange and receive timestamps, retain sequence numbers where available, detect sequence gaps and mark stale feeds. Orders are rejected when required market data exceeds the configured age threshold. A disconnected, stale or unresolved-gap feed must fail closed for strategies that depend on it.

## Order safety

Every order intent carries an idempotency key and deterministic client order ID. Execution checks idempotency before submission. Production live must use a durable atomic idempotency store and broker-side client-order deduplication when available.

Risk limits include at minimum: order notional, aggregate/absolute position, instrument allowlist, trading hours, drawdown, daily loss, liquidity/ADV participation and market-data freshness.

An independent kill switch must be enforceable without LLM/model cooperation. When engaged, new orders are rejected deterministically.

## Logs and evidence

Risk decisions, order intents, broker acknowledgements, fills, cancellations, position snapshots, reconciliation results, security events and configuration/risk-limit changes must be written to append-only/immutable storage or a tamper-evident equivalent. Audit records are hash-chainable and reference run/commit/source/version information.

No secret material may be written to logs.

## Reconciliation

Broker positions, cash, orders and fills are reconciled independently against the internal ledger. Material mismatch blocks promotion and may engage the kill switch according to policy. Reconciliation is required in paper/shadow and mandatory before/during live.

## Archive policy

Before extraction/opening, ZIP members are checked for absolute paths, `..` traversal, NUL bytes, symlinks, excessive member count, excessive uncompressed size and implausible compression ratio. Nested archives are subject to the same validation at every layer.

## Google Cloud Build and supply chain

- GitHub is the source repository; it is not the execution environment.
- Google Cloud Build is the canonical CI/CD executor.
- Validation builds must not use the privileged deploy service account.
- The deploy pipeline is manual, consumes promoted code, rejects destructive Terraform plans and deploys only immutable image digests.
- Dependency, static-analysis, source-integration and secret scans execute before deployment.
- Cloud Build container images are pinned by immutable digests.
- PAPER/SHADOW runtime uses a dedicated Cloud Run service account with no broker credential.
- Google Cloud Scheduler may invoke only the private PAPER/SHADOW job through the bounded scheduler identity.
- No static service-account key is permitted.
- Dependency vulnerability and secret scans fail closed.

## Data leakage controls

Static identity may use later evidence only when explicitly tagged `historical_identity`; economic/fundamental values remain publication-gated. Every row derived with later identity evidence keeps that fact. Future revisions of CVM/B3 snapshots are separate vintages.

## Security test matrix

Before live, automated or controlled tests must cover at minimum:

- order duplication;
- webhook replay;
- stale market data;
- API/host spoofing;
- webhook signature spoofing;
- credential leak detection;
- race conditions;
- idempotency-key misuse/failure;
- kill-switch enforcement;
- risk rejection preventing broker submission.

## Live promotion boundary

Promotion sequence is:

`backtest -> walk-forward -> paper -> shadow -> reconciliation -> security test -> risk validation -> live`

All mandatory gates must be explicitly green. Missing, stale or failed evidence means fail closed. Real money remains blocked until the complete gate set passes. AI can recommend and monitor, but can never bypass Risk Engine, Execution Engine, credential isolation, kill switch or reconciliation.

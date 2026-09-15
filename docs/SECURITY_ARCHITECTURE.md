# Security Architecture

## Security objectives

The research platform must protect four things independently: source integrity, point-in-time correctness, confidential operational information, and execution safety. A successful backtest based on corrupted/revised data is treated as a security failure, not only a research error.

## Threat model

Primary threats are: credential leakage; malicious or compromised upstream files; ZIP/path traversal and decompression bombs; source substitution or silent upstream revision; accidental publication of proprietary research; dependency/supply-chain compromise; untrusted pull-request code gaining write/secrets access; model/data poisoning; data leakage/look-ahead; unauthorized live trading; and irreversible deletion/overwrite of raw evidence.

## Trust boundaries

- **External sources:** untrusted until HTTPS host, response size, archive safety and digest are validated.
- **Raw vault/object storage:** append-only logical layer. Revisions create new vintages; they do not overwrite evidence.
- **Normalization/PIT layer:** deterministic transforms only, with lineage back to raw digests.
- **Feature/model layer:** consumes approved PIT contracts only. No direct web/API fetches inside backtests.
- **Execution layer:** separate credentials and permissions; unavailable to research jobs. Risk manager has independent veto.

## Required provenance manifest

Each external object must record at minimum:

- source URL and canonical source name;
- retrieval timestamp in UTC;
- content byte size;
- SHA-256;
- source publication/reference timestamp if known;
- parser/schema version;
- upstream identifier/file name;
- parent digest(s) for derived datasets;
- run/commit identifier.

## Network policy

Ingestion helpers default-deny unknown hosts and require HTTPS. Redirects must be revalidated. URLs containing embedded username/password are rejected. Timeouts and maximum response sizes are mandatory. Research/backtest code should operate from persisted approved snapshots, not the public network.

## Archive policy

Before extraction/opening, ZIP members are checked for absolute paths, `..` traversal, NUL bytes, symlinks, excessive member count, excessive uncompressed size and implausible compression ratio. Nested archives are subject to the same validation at every layer.

## GitHub Actions

- Repository permissions default to `contents: read`.
- Checkout uses `persist-credentials: false`.
- Security checks run on pull requests and main.
- Network audit workflows have read-only repository permissions and never consume privileged secrets.
- Dependency and static-analysis jobs are isolated from any execution/broker environment.

## Data leakage controls

Static identity may use later evidence only when explicitly tagged `historical_identity`; economic/fundamental values must remain publication-gated. Every row derived with later identity evidence keeps that fact. Future revisions of CVM/B3 snapshots are separate vintages.

## Live execution boundary

Research code has no authority to place real orders. Promotion sequence is research -> independent validation -> shadow/paper -> explicit human approval -> restricted live runtime. Position, drawdown, concentration and kill-switch limits are deterministic and cannot be overridden by an LLM/model recommendation.

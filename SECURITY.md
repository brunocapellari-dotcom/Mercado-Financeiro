# Security Policy

## Scope

This repository processes public market/regulatory data and research outputs. It must not contain brokerage credentials, cloud credentials, API secrets, personal financial records, client data, private keys, or raw licensed datasets that are not explicitly approved for source control.

## Mandatory controls

- Raw source files are immutable outside Git and identified by SHA-256.
- Every external dataset must retain source URL, retrieval time, reference/publication time when available, byte size and digest.
- Network ingestion is HTTPS-only and allowlisted by source host.
- Archives are validated before extraction for path traversal, symlinks, excessive member count, excessive expansion and suspicious compression ratios.
- Secrets never enter code, logs, manifests, issue bodies or committed configuration.
- GitHub Actions run with least-privilege `contents: read` unless a workflow has a documented exception.
- Pull-request workflows must not expose privileged secrets to untrusted code.
- Research datasets and model outputs must preserve point-in-time lineage; later revisions cannot silently overwrite earlier vintages.
- Production/live capital remains disabled unless the independent data, model and risk gates are approved.

## Data classes

1. **PUBLIC_SOURCE** — public B3/CVM/BCB/etc. data. May be downloaded by approved ingestion code; large raws stay outside Git.
2. **INTERNAL_RESEARCH** — features, backtests, model diagnostics and proprietary methodology. Private-repository only; do not publish without explicit approval.
3. **CONFIDENTIAL_OPERATIONAL** — account identifiers, portfolio/order data, execution logs, broker configuration. Must be stored only in approved protected services with least-privilege access and encryption at rest/in transit.
4. **SECRET** — tokens, passwords, keys, certificates and recovery material. Secret-manager only; never persist in repository, Drive documents, issue text or model prompts.

## Incident response

If a secret or confidential record is exposed: stop the affected workflow, rotate/revoke the credential first, preserve an audit record, remove the material from current Git history, assess downstream access/log exposure, and only then resume. Deleting a file without rotating the credential is not considered remediation.

## Reporting

Security findings should be handled privately and must not include active credentials or sensitive values in GitHub issues.
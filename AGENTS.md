# Mercado Financeiro — agent operating contract

This repository is the single development source of truth for Mercado Financeiro. Any coding agent or external development environment — including Claude Code, Replit, Codex or future tools — must work from a Git branch and return all changes to GitHub for the same complete project gates.

## Non-negotiable rules

- Preserve the six-layer boundary: DADOS -> INTELIGENCIA -> PREVISAO -> SINAL -> RISCO -> EXECUCAO.
- Historical research is point-in-time only. Never use future filings, current-universe backfills, future corporate actions or future identity evidence for economic signals.
- Static historical identity reconstruction may use later evidence only when explicitly classified as identity reconstruction and never as economic information.
- Raw official source artifacts and their hashes remain canonical evidence.
- Fail closed on ambiguous issuer/security identity, schema drift, stale/live data uncertainty, missing risk state or missing execution reconciliation.
- No live capital deployment until every source, research, risk, execution, security and reconciliation gate is green.
- Never weaken tests, remove provenance or lower acceptance thresholds merely to obtain a green build.
- Avoid duplicate frameworks, stores, schedulers or feature systems. Replace an existing component only when the replacement is objectively better and passes full regression.

## Required validation before handoff

Run the complete suite, not a narrow module test. The GitHub `full-project-gate` is authoritative and includes deterministic tests, security checks and live official-source integration audits. Local green results do not override a failing GitHub gate.

## Google Cloud boundary

Read `docs/GOOGLE_CLOUD_READINESS.md` before any cloud work. No agent may create Google Cloud resources, credentials, broker integrations or live infrastructure until an explicitly reviewed deployment change exists in this repository and the full project is green.

## Replit / Claude Code / other environments

They are development surfaces, not alternate repositories or deployment authorities. Clone from GitHub, work on a branch, preserve these contracts, and push the result back for CI. Do not maintain divergent copies or hidden production configuration outside the repository-controlled process.

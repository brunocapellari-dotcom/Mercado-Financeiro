# Mercado Financeiro — agent operating contract

This repository is the single development source of truth for Mercado Financeiro.
Coding agents and external development environments must work from a Git branch and
return every change to the same repository.

## Non-negotiable rules

- Preserve DADOS -> INTELIGENCIA -> PREVISAO -> SINAL -> RISCO -> EXECUCAO.
- LLM/Research produces hypotheses, never executable orders.
- Historical research is point-in-time only. Never backfill future filings,
  restatements, corporate actions, current-universe membership or future identity
  evidence into economic signals.
- Static identity reconstruction may use later evidence only when explicitly
  classified as identity reconstruction and never as economic information.
- Raw official artifacts and hashes remain canonical evidence.
- Fail closed on schema drift, ambiguous identity, stale data, missing risk state,
  unknown tool authority and unreconciled execution.
- No live capital until every source, research, risk, execution, security and
  reconciliation gate is green.
- Never weaken tests, provenance, thresholds or red-team cases to obtain green.
- Avoid duplicate frameworks, stores, schedulers and feature systems. Replace a
  component only when the replacement reduces total complexity and passes full
  regression.

## Canonical validation

The validation contract is repository-owned:

`python scripts/run_full_project_gate.py --mode full`

Run the complete gate, not a narrow module suite. GitHub Actions is one executor of
this contract, not the definition of correctness. Local, self-hosted, Cloud Build
or another authorized executor is acceptable only when it executes the same commit
and same gate without disabling checks.

A commit without executed gate evidence is **not validated**.

## Research-agent boundary

Pydantic AI Harness is optional infrastructure behind project adapters. Tool access
is fail-closed. Broker, execution, risk mutation, kill-switch and live namespaces
are forbidden to research agents. Promptfoo/Pydantic Evals regression failures
block promotion of the agent surface.

## Google Cloud boundary

Read `docs/GOOGLE_CLOUD_READINESS.md` before cloud work. No agent may create
production cloud resources, broker connections or live credentials until an
explicitly reviewed deployment change exists and the complete project gate is green.

## Development surfaces

Replit, Claude Code, Codex and similar tools are development surfaces, not alternate
repositories or deployment authorities. Do not create divergent copies, hidden
production configuration or independent live paths.

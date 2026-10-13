# Execution cycle — 50-task audit — 2026-09-29

This document maps the requested 50-task cycle to repository evidence. "Implemented"
means code/contracts/tests exist in the PR branch. "Blocked validation" means the
artifact exists but the canonical full-project executor has not produced a green
run for the current head.

| # | Task | State | Evidence |
|---:|---|---|---|
| 1 | Cloud whole-project pipeline | implemented / blocked validation | cloudbuild.yaml + full-project gate |
| 2 | build/dependency/test repairs | blocked validation | requires executed gate |
| 3 | uv/lock reproducibility | blocked resolver | no fabricated lock committed |
| 4 | quality/type/test consolidation | implemented | pyproject + runner-independent gate |
| 5 | clean installation validation | configured / blocked validation | clean Cloud Build containers |
| 6 | commit/config reproducibility | implemented | provenance manifests + commit-bound evidence |
| 7 | module inventory / deduplication | implemented | consolidated architecture and CI |
| 8 | architecture dependency map | implemented | docs/ARCHITECTURE.md |
| 9 | canonical typed contracts | implemented | architecture/signal/forecast/risk contracts |
| 10 | B3 security master | implemented | pit/security_master.py |
| 11 | canonical identities | implemented | ISIN/CNPJ/ticker PIT identity stack |
| 12 | historical identity/reorganizations | implemented | registry/FCA/verified identity |
| 13 | corporate actions PIT | implemented | pit/corporate_actions.py |
| 14 | splits/cash/event lifecycle | implemented | corporate action lifecycle + total return |
| 15 | delisting/survivorship controls | implemented | pit/survivorship.py + universe gates |
| 16 | B3 observed calendar | implemented | execution/calendar.py |
| 17 | corporate-event lifecycle | implemented | b3/company_events.py |
| 18 | B3 historical prices | implemented | COTAHIST PIT |
| 19 | CVM issuer data | implemented | CVM/FCA/FRE stack |
| 20 | DFP/ITR/FRE foundation | implemented | CVM PIT readers/audits |
| 21 | accounting normalization | implemented in this cycle | pit/accounting_normalization.py |
| 22 | PIT fundamentals | implemented | data/fundamentals.py |
| 23 | restatement/version handling | implemented | filing_version + available_from |
| 24 | BCB SGS/PTAX/Focus | implemented in this cycle | data/bcb.py + data/bcb_olinda.py |
| 25 | ANBIMA source boundary | implemented | data/anbima.py |
| 26 | NEFIN | implemented | data/nefin.py |
| 27 | macro vintage contract | implemented | data/macro.py; Focus conservative vintage |
| 28 | immutable RAW | implemented | security/raw_vault.py |
| 29 | normalized schemas | implemented | data/source_contracts.py |
| 30 | FEATURES layer | implemented | research/features.py |
| 31 | lineage | implemented | feature manifests + provenance |
| 32 | look-ahead tests | implemented | feature/source/PIT tests |
| 33 | survivorship tests | implemented | tradable universe + identity gates |
| 34 | data leakage controls | implemented | cutoff/PIT/training-serving tests |
| 35 | time/session/availability | implemented | B3 calendar + PIT semantics |
| 36 | purged CV/embargo | implemented | research/purged_cv.py |
| 37 | walk-forward | implemented | research/tournament.py |
| 38 | Deflated Sharpe | implemented | research/tournament.py |
| 39 | PBO | implemented | research/tournament.py |
| 40 | external engine benchmark contract | implemented / runtime blocked | engine_parity + policy |
| 41 | Nautilus scope | implemented | benchmark-only RC policy |
| 42 | strategy/factor catalogue | implemented in this cycle | research/catalog.py |
| 43 | five factor baselines | implemented in this cycle | research/factors.py |
| 44 | Brazilian multifactor model | implemented in this cycle | PIT composite + NEFIN-compatible OLS validation |
| 45 | implementation costs and tax boundary | implemented | execution/brokerage.py + accounting/tax.py; statutory rates require audited official rule sets |
| 46 | portfolio constraints | implemented | risk/portfolio.py |
| 47 | deterministic Risk Manager | implemented | risk/engine.py + authority firewall |
| 48 | accounting/paper foundations | implemented | ledger + execution/reconciliation/runtime |
| 49 | full backtest/Monte Carlo/stress execution | engine implemented / execution blocked | tournament + block-bootstrap + historical stress require whole-project executor/data run |
| 50 | readiness gate | implemented / blocked final pass | architecture/final_gate.py |

## Acceptance interpretation

Code presence is not equivalent to production readiness. The branch must not merge
until the deterministic gate and every official-source audit execute successfully on
the current head. LIVE remains disabled even after merge until paper/shadow,
reconciliation, security and independent risk gates are explicitly green.

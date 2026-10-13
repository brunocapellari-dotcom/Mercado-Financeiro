# Mercado Financeiro — Release Gate

Data: 2026-10-13

Regra: **DONE = código + teste executado + evidência + commit**.

GitHub é a fonte de código. **Google Cloud Build é o executor canônico. GitHub Actions não é usado.**

## Baseline verde comprovado

Commit `024ded70b2d28921ba36de1feb9d4bb144edc0c2` passou integralmente no executor anteriormente disponível:

- Python 3.11 / 3.12;
- CodeQL;
- dependency/security gates;
- B3/CVM identity;
- FRE;
- BVBG;
- CVM PIT;
- BCB/macro;
- B3 corporate events;
- source diagnostics.

## Estado atual

| Componente | Estado | Evidência / condição |
|---|---|---|
| Core PIT / anti-lookahead | DONE | Testes e baseline verde. |
| Risk Manager | DONE core | Fail-closed pré-trade e limites determinísticos. |
| Simulated execution/accounting | DONE core | Mesmo path para backtest/PAPER, sem broker real. |
| Historical official sources | DONE baseline | B3/CVM/BCB/NEFIN gates verdes no baseline. |
| BRAPI adapter | READY FOR GOOGLE VALIDATION | Adapter v2, retry, allowlist, provenance e testes adicionados. |
| Zero-cost market data | READY FOR GOOGLE VALIDATION | Sandbox PETR4/VALE3/MGLU3/ITUB4; delayed only. |
| PAPER market cycle | READY FOR GOOGLE VALIDATION | Stale/out-of-window = skip; no fake execution. |
| Docker runtime | READY FOR GOOGLE VALIDATION | Non-root; cloud extras incluídos. |
| BigQuery layers | READY FOR GOOGLE VALIDATION | raw/normalized/canonical/derived/analytics/research. |
| Cloud Run Job | READY FOR DEPLOY | Private `mf-paper-shadow`; no LIVE credentials. |
| Cloud Scheduler | READY FOR DEPLOY | 30-min market-hour cadence. |
| Immutable evidence | READY FOR DEPLOY | GCS append-only object create. |
| Google Cloud Build gate | READY | `cloudbuild.yaml`. |
| Google deploy pipeline | READY | `cloudbuild.deploy.yaml`; destructive plans blocked. |
| E2E #1/#2 | BLOCKED EXTERNALLY | Requires first Google Cloud Build/deploy execution. |
| LIVE money | BLOCKED BY DESIGN | Explicitly outside this release. |

## Human/GCP dependency

Before the first real Google deployment:

1. Cloud Build must be connected to the Mercado-Financeiro GitHub repository.
2. Verify/grant to `github-deployer@ai-holding-prod-bc.iam.gserviceaccount.com`:
   - `roles/bigquery.admin`;
   - `roles/storage.admin`;
   - `roles/logging.logWriter`.

Do not create a JSON service-account key. Do not restore GitHub Actions/WIF for this project.

After those permissions exist, run `cloudbuild.deploy.yaml`. The pipeline itself performs plan/apply, IAM checks, two acceptance executions and evidence persistence.

# Mercado Financeiro — Google Cloud PAPER/SHADOW

Target:

- project: `ai-holding-prod-bc`;
- region: `southamerica-east1`;
- executor: Google Cloud Build;
- runtime: Cloud Run Jobs;
- cadence: Cloud Scheduler;
- image registry: existing Holding Artifact Registry `holding`;
- Terraform state: `gs://ai-holding-prod-bc-tfstate/mercado-financeiro/prod`.

GitHub Actions is not used.

## Data plane

Datasets:

- `mf_raw`;
- `mf_normalized`;
- `mf_canonical`;
- `mf_derived`;
- `mf_analytics`;
- `mf_research`.

The raw evidence bucket is private, versioned, public-access-prevention enabled and non-destructive by default.

## PAPER/SHADOW runtime

`mf-paper-shadow`:

- dedicated service account;
- no broker credential;
- no LIVE adapter;
- BRAPI delayed polling market data;
- default zero-cost sandbox ticker PETR4;
- freshness gate;
- simulated fills only;
- 1 vCPU / 512 MiB;
- operational evidence written append-only to GCS.

Scheduler:

- `mf-paper-shadow-market-hours`;
- default every 30 minutes, weekdays, 10:00–17:59 America/Sao_Paulo;
- bounded retry;
- invokes only the private Cloud Run Job.

## Build and deploy

`cloudbuild.yaml` validates the repository.

`cloudbuild.deploy.yaml` performs the production PAPER/SHADOW deployment and two mandatory acceptance runs.

Images are accepted only by immutable Artifact Registry digest.

Terraform rejects automatic destruction through explicit release checks and protected resources.

## One-time Google dependency

Connect the GitHub repository to Cloud Build and verify the deploy service account permissions.

The existing deployer from the Holding is reused:
`github-deployer@ai-holding-prod-bc.iam.gserviceaccount.com`.

Additional project roles required by this stack if not already present:

- `roles/bigquery.admin`;
- `roles/storage.admin`;
- `roles/logging.logWriter`.

No static key should be created.

## Market data

BRAPI is deliberately isolated to PAPER/SHADOW. It does not replace B3/CVM canonical historical data and must not be promoted to LIVE execution.

The no-key sandbox is limited to the documented sandbox tickers enforced in `variables.tf`. Broader coverage later can use a BRAPI key or another licensed provider without changing the vendor-neutral market-data interface.

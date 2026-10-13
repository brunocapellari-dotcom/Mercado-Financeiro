# Mercado Financeiro — Google Cloud PAPER/SHADOW data plane

This Terraform stack targets the shared AI Holding Google Cloud project
`ai-holding-prod-bc` in `southamerica-east1`.

It does not create a parallel cloud platform. It reuses the Holding foundation and
declares Mercado Financeiro-specific resources only:

- private/versioned GCS raw-evidence bucket;
- BigQuery datasets for `raw`, `normalized`, `canonical`, `derived`,
  `analytics` and isolated `research`;
- least-privilege ingest/transform/research/read-only service accounts;
- dedicated `mf-paper-shadow` runtime service account;
- Secret Manager metadata `mf-authorized-price-report-url`;
- private Cloud Run Job `mf-paper-shadow`, disabled by default;
- invoker binding for the existing Holding bounded scheduler identity.

## Safety defaults

`deploy_paper_shadow=false` by default.

The job cannot be created unless `runtime_image_ref` is an immutable
`@sha256:` reference inside the shared Holding Artifact Registry.

LIVE trading is not represented by any Terraform variable, identity, secret or
resource in this stack.

The market-data secret contains no version in Terraform. A human must first provide
an authorized/licensed current market-data source and add its secret version outside
source control.

## State

Production state uses the existing Holding state bucket:

- bucket: `ai-holding-prod-bc-tfstate`;
- prefix: `mercado-financeiro/prod`.

Do not share the Holding Control Plane Terraform state.

## Evidence

Operational PAPER/SHADOW evidence is written append-only under
`operational/mercado-financeiro/` in the same versioned raw-evidence bucket. The
runtime has `roles/storage.objectCreator`, not object delete/update permissions.

## Deployment gate

Before apply:

1. full-project-gate and CodeQL green on the same commit;
2. Terraform fmt/init/validate green;
3. container build and PAPER smoke green;
4. Holding WIF PR #67 approved/applied;
5. authorized market-data secret version present;
6. Terraform plan contains no delete action.

The manual `deploy-paper-shadow` workflow then applies the plan and requires two
successful Cloud Run Job executions without code/config edits.

Never add service-account JSON keys, broker credentials, public buckets, project
Owner/Editor roles, or destructive automatic teardown.

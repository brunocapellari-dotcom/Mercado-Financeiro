# Mercado Financeiro Google Cloud data plane

Declarative infrastructure only; this directory is never auto-applied by tests.

It creates four isolated BigQuery datasets, a private versioned raw-evidence bucket,
and separate ingest, transform, research and read-only service accounts.

Before apply, the whole-project gate, Terraform validation and a reviewed plan must
be green. Confirm the selected data location and raw-source retention/licensing.
Use short-lived Workload Identity Federation credentials. Never add service-account
JSON keys, broker credentials, public buckets, project Owner/Editor roles, or
destructive automatic teardown.

LIVE trading identities are deliberately outside this data plane.

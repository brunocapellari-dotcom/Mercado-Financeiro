locals {
  holding_scheduler_service_account = "holding-worker-scheduler@${var.project_id}.iam.gserviceaccount.com"
  execution_evidence_bucket         = google_storage_bucket.raw_evidence.name
}

resource "google_service_account" "paper_shadow" {
  account_id   = "mf-paper-shadow"
  display_name = "Mercado Financeiro PAPER/SHADOW"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_storage_bucket_iam_member" "paper_shadow_evidence_writer" {
  bucket = local.execution_evidence_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.paper_shadow.email}"
}

resource "google_cloud_run_v2_job" "paper_shadow" {
  count               = var.deploy_paper_shadow ? 1 : 0
  name                = "mf-paper-shadow"
  location            = var.region
  deletion_protection = true

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = (
        !var.deploy_paper_shadow
        || (
          startswith(
            var.runtime_image_ref,
            "${var.region}-docker.pkg.dev/${var.project_id}/holding/"
          )
          && strcontains(var.runtime_image_ref, "@sha256:")
        )
      )
      error_message = "runtime_image_ref must be an immutable digest in the shared Holding Artifact Registry."
    }
  }

  template {
    template {
      service_account = google_service_account.paper_shadow.email
      timeout         = "1800s"
      max_retries     = 1

      containers {
        image = var.runtime_image_ref
        args = [
          "--mode",
          "paper",
          "--output",
          "/tmp/mercado-financeiro-operational-evidence.json",
        ]

        env {
          name  = "MF_PAPER_TICKER"
          value = var.paper_ticker
        }

        env {
          name  = "MF_PAPER_MAX_QUOTE_AGE_SECONDS"
          value = tostring(var.paper_max_quote_age_seconds)
        }

        env {
          name  = "MF_PAPER_SYNTHETIC_SPREAD_BPS"
          value = tostring(var.paper_synthetic_spread_bps)
        }

        env {
          name  = "MF_EVIDENCE_BUCKET"
          value = local.execution_evidence_bucket
        }

        env {
          name  = "MF_EVIDENCE_PREFIX"
          value = "operational/mercado-financeiro"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.paper_shadow_evidence_writer,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "holding_scheduler_invoker" {
  count    = var.deploy_paper_shadow ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.paper_shadow[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.holding_scheduler_service_account}"
}

resource "google_cloud_scheduler_job" "paper_shadow" {
  count       = var.deploy_paper_shadow ? 1 : 0
  name        = "mf-paper-shadow-market-hours"
  description = "Runs the delayed PAPER/SHADOW operational cycle on Google infrastructure."
  region      = var.region
  schedule    = var.paper_shadow_schedule
  time_zone   = "America/Sao_Paulo"

  retry_config {
    retry_count          = 1
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri = (
      "https://run.googleapis.com/v2/projects/${var.project_id}/locations/"
      + "${var.region}/jobs/${google_cloud_run_v2_job.paper_shadow[0].name}:run"
    )

    oauth_token {
      service_account_email = local.holding_scheduler_service_account
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_cloud_run_v2_job_iam_member.holding_scheduler_invoker,
  ]
}

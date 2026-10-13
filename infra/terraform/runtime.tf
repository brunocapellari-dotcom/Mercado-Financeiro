locals {
  holding_scheduler_service_account = "holding-worker-scheduler@${var.project_id}.iam.gserviceaccount.com"
  execution_evidence_bucket         = "${var.project_id}-ai-execution-evidence"
}

resource "google_service_account" "paper_shadow" {
  account_id   = "mf-paper-shadow"
  display_name = "Mercado Financeiro PAPER/SHADOW"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "authorized_price_report_url" {
  secret_id = var.market_data_secret_id

  replication {
    auto {}
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret_iam_member" "paper_shadow_market_data" {
  secret_id = google_secret_manager_secret.authorized_price_report_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.paper_shadow.email}"
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
          "full",
          "--output",
          "/tmp/mercado-financeiro-operational-evidence.json",
        ]

        env {
          name  = "MF_PRICE_REPORT_DATASET"
          value = var.price_report_dataset
        }

        env {
          name  = "MF_PAPER_TICKER"
          value = var.paper_ticker
        }

        env {
          name = "MF_PRICE_REPORT_URL"

          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.authorized_price_report_url.secret_id
              version = "latest"
            }
          }
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
    google_secret_manager_secret_iam_member.paper_shadow_market_data,
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

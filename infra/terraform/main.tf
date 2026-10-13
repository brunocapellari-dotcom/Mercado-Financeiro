terraform {
  required_version = ">= 1.9.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  datasets = toset(["raw", "normalized", "canonical", "derived", "analytics", "research"])
  service_accounts = {
    ingest    = "mf-ingest"
    transform = "mf-transform"
    research  = "mf-research"
    reader    = "mf-reader"
  }
}

resource "google_storage_bucket" "raw_evidence" {
  name                        = "${var.project_id}-mf-raw-evidence"
  location                    = var.location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.raw_retention_seconds
    is_locked        = false
  }
}

resource "google_bigquery_dataset" "layer" {
  for_each                   = local.datasets
  dataset_id                 = "mf_${each.key}"
  friendly_name              = "Mercado Financeiro ${each.key}"
  description                = "Canonical Mercado Financeiro ${each.key} data layer"
  location                   = var.location
  delete_contents_on_destroy = false

  labels = {
    system = "mercado-financeiro"
    layer  = each.key
  }
}

resource "google_service_account" "workload" {
  for_each     = local.service_accounts
  account_id   = each.value
  display_name = "Mercado Financeiro ${each.key}"
}

resource "google_storage_bucket_iam_member" "ingest_raw_writer" {
  bucket = google_storage_bucket.raw_evidence.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.workload["ingest"].email}"
}

resource "google_storage_bucket_iam_member" "transform_raw_reader" {
  bucket = google_storage_bucket.raw_evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_bigquery_dataset_iam_member" "raw_ingest_editor" {
  dataset_id = google_bigquery_dataset.layer["raw"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["ingest"].email}"
}

resource "google_bigquery_dataset_iam_member" "raw_transform_reader" {
  dataset_id = google_bigquery_dataset.layer["raw"].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  for_each = toset(["ingest", "transform", "research"])
  project  = var.project_id
  role     = "roles/bigquery.jobUser"
  member   = "serviceAccount:${google_service_account.workload[each.key].email}"
}

resource "google_bigquery_dataset_iam_member" "normalized_transform_editor" {
  dataset_id = google_bigquery_dataset.layer["normalized"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_bigquery_dataset_iam_member" "canonical_transform_editor" {
  dataset_id = google_bigquery_dataset.layer["canonical"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_bigquery_dataset_iam_member" "derived_transform_editor" {
  dataset_id = google_bigquery_dataset.layer["derived"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_bigquery_dataset_iam_member" "analytics_transform_editor" {
  dataset_id = google_bigquery_dataset.layer["analytics"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["transform"].email}"
}

resource "google_bigquery_dataset_iam_member" "research_reader" {
  for_each   = toset(["normalized", "canonical", "derived", "analytics"])
  dataset_id = google_bigquery_dataset.layer[each.key].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.workload["research"].email}"
}

resource "google_bigquery_dataset_iam_member" "research_writer" {
  dataset_id = google_bigquery_dataset.layer["research"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.workload["research"].email}"
}

resource "google_bigquery_dataset_iam_member" "readonly_viewer" {
  for_each   = local.datasets
  dataset_id = google_bigquery_dataset.layer[each.key].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.workload["reader"].email}"
}

output "raw_evidence_bucket" {
  value = google_storage_bucket.raw_evidence.name
}

output "dataset_ids" {
  value = { for key, dataset in google_bigquery_dataset.layer : key => dataset.dataset_id }
}

output "service_accounts" {
  value = { for key, account in google_service_account.workload : key => account.email }
}

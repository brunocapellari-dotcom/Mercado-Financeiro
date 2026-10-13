output "raw_evidence_bucket" {
  value = google_storage_bucket.raw_evidence.name
}

output "dataset_ids" {
  value = { for key, dataset in google_bigquery_dataset.layer : key => dataset.dataset_id }
}

output "service_accounts" {
  value = { for key, account in google_service_account.workload : key => account.email }
}


output "paper_shadow_service_account" {
  value = google_service_account.paper_shadow.email
}

output "paper_shadow_job" {
  value = var.deploy_paper_shadow ? google_cloud_run_v2_job.paper_shadow[0].name : null
}


output "paper_shadow_scheduler" {
  value = var.deploy_paper_shadow ? google_cloud_scheduler_job.paper_shadow[0].name : null
}

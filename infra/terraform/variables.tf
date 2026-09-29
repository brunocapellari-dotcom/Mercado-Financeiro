variable "project_id" {
  type        = string
  description = "Google Cloud project ID."
}

variable "region" {
  type        = string
  default     = "southamerica-east1"
  description = "Default Google Cloud region."
}

variable "location" {
  type        = string
  default     = "southamerica-east1"
  description = "Storage/BigQuery location; verify service compatibility before apply."
}

variable "raw_retention_seconds" {
  type        = number
  default     = 2592000
  description = "Unlocked minimum raw-evidence retention; lock only after legal/licensing review."
}

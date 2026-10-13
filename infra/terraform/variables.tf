variable "project_id" {
  type        = string
  default     = "ai-holding-prod-bc"
  description = "Shared AI Holding Google Cloud project ID."
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

variable "deploy_paper_shadow" {
  type        = bool
  default     = false
  description = "Create the PAPER/SHADOW Cloud Run Job and Google Cloud Scheduler. LIVE is never enabled here."
}

variable "runtime_image_ref" {
  type        = string
  default     = ""
  description = "Immutable Mercado Financeiro runtime image digest in the shared Holding Artifact Registry."
}

variable "paper_ticker" {
  type        = string
  default     = "PETR4"
  description = "BRAPI sandbox ticker used for zero-cost PAPER/SHADOW operational validation."

  validation {
    condition     = contains(["PETR4", "VALE3", "MGLU3", "ITUB4"], var.paper_ticker)
    error_message = "Without a BRAPI key, paper_ticker must be one of the documented sandbox tickers: PETR4, VALE3, MGLU3 or ITUB4."
  }
}

variable "paper_max_quote_age_seconds" {
  type        = number
  default     = 2400
  description = "Maximum delayed quote age tolerated by PAPER/SHADOW; never applies to LIVE."

  validation {
    condition     = var.paper_max_quote_age_seconds >= 300 && var.paper_max_quote_age_seconds <= 7200
    error_message = "paper_max_quote_age_seconds must be between 300 and 7200 seconds."
  }
}

variable "paper_synthetic_spread_bps" {
  type        = number
  default     = 20
  description = "Conservative synthetic spread around delayed last price for PAPER only."

  validation {
    condition     = var.paper_synthetic_spread_bps >= 1 && var.paper_synthetic_spread_bps <= 200
    error_message = "paper_synthetic_spread_bps must be between 1 and 200 bps."
  }
}

variable "paper_shadow_schedule" {
  type        = string
  default     = "*/30 10-17 * * 1-5"
  description = "Cloud Scheduler cron in America/Sao_Paulo for delayed PAPER/SHADOW polling."
}

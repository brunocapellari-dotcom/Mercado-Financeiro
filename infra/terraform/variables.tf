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
  description = "Create the PAPER/SHADOW Cloud Run Job. LIVE trading is never enabled here."
}

variable "runtime_image_ref" {
  type        = string
  default     = ""
  description = "Immutable Mercado Financeiro runtime image digest in the shared Holding Artifact Registry."
}

variable "market_data_secret_id" {
  type        = string
  default     = "mf-authorized-price-report-url"
  description = "Secret Manager secret metadata for the authorized current market-data URL/token."
}

variable "price_report_dataset" {
  type        = string
  default     = "BVBG.186.01"
  description = "Authorized B3 price-report dataset contract used by PAPER/SHADOW preflight."

  validation {
    condition     = contains(["BVBG.086.01", "BVBG.186.01"], var.price_report_dataset)
    error_message = "price_report_dataset must be BVBG.086.01 or BVBG.186.01."
  }
}

variable "paper_ticker" {
  type        = string
  default     = "PETR4"
  description = "Liquid B3 ticker used only for PAPER/SHADOW operational preflight."

  validation {
    condition     = can(regex("^[A-Z0-9]{4,12}$", var.paper_ticker))
    error_message = "paper_ticker must be an uppercase B3-style symbol."
  }
}

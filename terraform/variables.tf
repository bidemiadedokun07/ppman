variable "project_id" {
  description = "GCP project ID (must already exist and have billing linked)"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment label, used in resource names (e.g. sandbox, staging, prod)"
  type        = string
  default     = "sandbox"
}

variable "embedding_dimensions" {
  description = "Vector dimensions produced by MODEL_EMBEDDING (768 for text-embedding-005)"
  type        = number
  default     = 768
}

variable "cloudsql_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is cheapest, fine for a sandbox."
  type        = string
  default     = "db-f1-micro"
}

variable "vector_search_machine_type" {
  description = "Machine type for the deployed Vector Search index. e2-standard-2 is the smallest practical size."
  type        = string
  default     = "e2-standard-2"
}

variable "vector_search_min_replicas" {
  description = "Minimum serving replicas for the deployed index. Keep at 1 for a sandbox to minimize cost; this is the main ongoing cost driver, see the Execution Guide's cost note."
  type        = number
  default     = 1
}

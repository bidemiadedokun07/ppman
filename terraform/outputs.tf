output "cloudsql_connection_name" {
  description = "Copy into .env as CLOUDSQL_INSTANCE_CONNECTION_NAME"
  value       = google_sql_database_instance.pipeman_db.connection_name
}

output "db_password" {
  description = "Copy into .env as CLOUDSQL_DB_PASSWORD (also stored in Secret Manager: pipeman-<env>-db-password)"
  value       = random_password.db_password.result
  sensitive   = true
}

output "vector_search_index_id" {
  description = "Copy into .env as VECTOR_SEARCH_INDEX_ID"
  value       = google_vertex_ai_index.pipeman_index.id
}

output "vector_search_endpoint_id" {
  description = "Copy into .env as VECTOR_SEARCH_ENDPOINT_ID"
  value       = google_vertex_ai_index_endpoint.pipeman_endpoint.id
}

output "documents_bucket" {
  description = "Cloud Storage bucket for staging source documents"
  value       = google_storage_bucket.documents.name
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository for container images"
  value       = google_artifact_registry_repository.pipeman_repo.repository_id
}

output "service_account_email" {
  description = "Pipeman application service account"
  value       = google_service_account.pipeman_app.email
}

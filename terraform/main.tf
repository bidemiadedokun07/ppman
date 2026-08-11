# ============================================================
# Pipeman infrastructure, matching the Design Document and
# Infrastructure Requirements doc component-for-component.
#
# Apply with: terraform init && terraform apply
# Tear down with: terraform destroy (see Execution Guide, cost note)
# ============================================================

locals {
  name_prefix   = "pipeman-${var.environment}"
  cloudbuild_sa = "${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

data "google_project" "current" {
  project_id = var.project_id
}

# ---------------------------------------------------------------
# 1. Enable required APIs
# ---------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "sqladmin.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ---------------------------------------------------------------
# 2. Service account and least-privilege IAM (see Infrastructure
#    Requirements doc, "IAM and Access")
# ---------------------------------------------------------------
resource "google_service_account" "pipeman_app" {
  account_id   = "${local.name_prefix}-app"
  display_name = "Pipeman application identity"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "app_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

resource "google_project_iam_member" "app_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

resource "google_project_iam_member" "app_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

# ---------------------------------------------------------------
# 2b. Cloud Build's own service account: newer projects do not
#     auto-grant this broad permissions, so pushing images and
#     deploying Cloud Run both need to be explicitly authorized.
# ---------------------------------------------------------------
resource "google_project_iam_member" "cloudbuild_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${local.cloudbuild_sa}"
}

resource "google_project_iam_member" "cloudbuild_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${local.cloudbuild_sa}"
}

# Deploying Cloud Run with a specific runtime service account (below)
# requires the deployer to be allowed to "act as" that service account.
resource "google_service_account_iam_member" "cloudbuild_act_as_app" {
  service_account_id = google_service_account.pipeman_app.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${local.cloudbuild_sa}"
}

# ---------------------------------------------------------------
# 2c. Your Cloud Build trigger runs AS pipeman_app (not Cloud
#     Build's default service account), confirmed via
#     `gcloud builds describe ... --format="value(serviceAccount)"`.
#     Grant the permissions the build itself needs directly to this
#     identity, since that is the one actually executing the build.
# ---------------------------------------------------------------
resource "google_project_iam_member" "app_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

resource "google_project_iam_member" "app_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

resource "google_project_iam_member" "app_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.pipeman_app.email}"
}

# ---------------------------------------------------------------
# 3. Cloud Storage: staging bucket for source documents
# ---------------------------------------------------------------
resource "google_storage_bucket" "documents" {
  name                        = "${var.project_id}-${local.name_prefix}-documents"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true # sandbox convenience; remove for production
  depends_on                  = [google_project_service.apis]
}

# ---------------------------------------------------------------
# 4. Cloud SQL for PostgreSQL: metadata store (chunks, reference
#    records, chat history, audit log). No pgvector extension here,
#    embeddings live in Vertex AI Vector Search below.
# ---------------------------------------------------------------
resource "random_password" "db_password" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "pipeman_db" {
  name             = "${local.name_prefix}-db"
  database_version = "POSTGRES_15"
  region           = var.region
  deletion_protection = false # sandbox convenience; set true for production

  settings {
    tier = var.cloudsql_tier
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "pipeman" {
  name     = "pipeman"
  instance = google_sql_database_instance.pipeman_db.name
}

resource "google_sql_user" "pipeman_app" {
  name     = "pipeman_app"
  instance = google_sql_database_instance.pipeman_db.name
  password = random_password.db_password.result
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "${local.name_prefix}-db-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

# ---------------------------------------------------------------
# 5. Artifact Registry: container images for Cloud Run / Cloud Build
# ---------------------------------------------------------------
resource "google_artifact_registry_repository" "pipeman_repo" {
  location      = var.region
  repository_id = "${local.name_prefix}-repo"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------
# 6. Vertex AI Vector Search: index + endpoint + deployment
#
# NOTE: the deployed-index resource below is a newer part of the
# Google Terraform provider's surface and has shifted between
# provider versions. Before running `terraform apply`, confirm the
# resource name and required arguments against the currently
# installed provider's docs (`terraform providers schema -json` or
# the Terraform Registry page for hashicorp/google). If it errors,
# the index and endpoint resources below will still succeed, and
# you can deploy the index to the endpoint with one `gcloud` command
# as a fallback (see the Execution Guide, Step 6).
# ---------------------------------------------------------------
resource "google_vertex_ai_index" "pipeman_index" {
  region       = var.region
  display_name = "${local.name_prefix}-index"
  description  = "Pipeman chunk and reference-record embeddings"

  metadata {
    contents_delta_uri = "gs://${google_storage_bucket.documents.name}/vector-search-init/"
    config {
      dimensions                  = var.embedding_dimensions
      approximate_neighbors_count = 100
      distance_measure_type       = "COSINE_DISTANCE"
      feature_norm_type           = "UNIT_L2_NORM"
      shard_size                  = "SHARD_SIZE_SMALL" # required to pair with e2-standard-2 below
      algorithm_config {
        tree_ah_config {}
      }
    }
  }

  index_update_method = "STREAM_UPDATE" # allows upsert_datapoints() from the ingestion pipeline

  depends_on = [google_project_service.apis]
}

resource "google_vertex_ai_index_endpoint" "pipeman_endpoint" {
  display_name = "${local.name_prefix}-endpoint"
  region       = var.region
  public_endpoint_enabled = true # sandbox convenience; use a private (VPC) endpoint for enterprise/IL5

  depends_on = [google_project_service.apis]
}

resource "google_vertex_ai_index_endpoint_deployed_index" "pipeman_deployed" {
  index_endpoint     = google_vertex_ai_index_endpoint.pipeman_endpoint.id
  index              = google_vertex_ai_index.pipeman_index.id
  deployed_index_id  = "pipeman_deployed_index"
  display_name       = "${local.name_prefix}-deployed"

  dedicated_resources {
    machine_spec {
      machine_type = var.vector_search_machine_type
    }
    min_replica_count = var.vector_search_min_replicas
    max_replica_count = var.vector_search_min_replicas
  }
}
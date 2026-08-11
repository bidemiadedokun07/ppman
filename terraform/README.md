# Pipeman Terraform

Provisions everything in the Infrastructure Requirements doc's "Core
Infrastructure" table: enabled APIs, a least-privilege service account,
Cloud Storage, Cloud SQL for PostgreSQL, Artifact Registry, and a Vertex
AI Vector Search index + endpoint + deployment.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # fill in your project_id
terraform init
terraform validate
terraform plan
terraform apply
```

After apply, copy the printed outputs into your `.env` file:

```bash
terraform output cloudsql_connection_name
terraform output -raw db_password
terraform output vector_search_index_id
terraform output vector_search_endpoint_id
```

## Before you apply: one thing to verify

The `google_vertex_ai_index_endpoint_deployed_index` resource is a newer
part of the provider's surface. If `terraform apply` errors on that
specific resource, comment it out, apply the rest, and deploy the index
manually with:

```bash
gcloud ai index-endpoints deploy-index ENDPOINT_ID \
  --index=INDEX_ID \
  --deployed-index-id=pipeman_deployed_index \
  --display-name=pipeman-deployed \
  --region=us-central1
```

Then set `VECTOR_SEARCH_DEPLOYED_INDEX_ID=pipeman_deployed_index` in `.env`
either way.

## Tear down

```bash
terraform destroy
```

The Vector Search endpoint deployment is the main ongoing cost while it
exists; destroying (or scaling `vector_search_min_replicas` down, which
Terraform does not support to zero, only full destroy does) is how you
stop that cost between sessions. See the Execution Guide's cost note.

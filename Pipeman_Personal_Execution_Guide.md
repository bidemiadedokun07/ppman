# Pipeman: Personal Sandbox Execution Guide

Build the real ingestion and retrieval pipelines end to end, on your own GCP account, with public data, using the exact same architecture (including Vertex AI Vector Search) you will use at work.

## How to use this guide

This walks through building Pipeman's two pipelines, offline ingestion and query-time retrieval, on your own GCP account using the companion codebase (`pipeman-app.zip`). Infrastructure is provisioned with Terraform, not one-off commands, so you get real, repeatable infrastructure-as-code practice, and can tear everything down cleanly the moment you've confirmed it works.

Follow the steps in order. Each one assumes the previous steps are done.

---

## Step 1: Prerequisites

| Requirement | Notes |
|---|---|
| Google account with billing enabled | A personal GCP account is fine; set a budget alert immediately (Step 12). |
| gcloud CLI installed | https://cloud.google.com/sdk/docs/install, run `gcloud init` after install. |
| Terraform installed | https://developer.hashicorp.com/terraform/install (v1.5+) |
| Python 3.11+ | Match the Dockerfile's runtime version to avoid local/deployed drift. |
| Git | For version control and the CI/CD walkthrough in Step 11. |
| A few public PDFs and Excel workbooks | Anything public, e.g. a published agency policy PDF and a sample spreadsheet, purely to exercise the pipeline end to end. |

---

## Step 2: Create the GCP project

```bash
gcloud projects create pipeman-sandbox-$(whoami) --name="Pipeman Sandbox"
gcloud config set project pipeman-sandbox-$(whoami)
gcloud billing projects link pipeman-sandbox-$(whoami) \
  --billing-account=YOUR_BILLING_ACCOUNT_ID
```

Terraform will enable the required APIs for you in Step 5, no need to do it manually.

---

## Step 3: Authenticate Terraform against your project

```bash
gcloud auth application-default login
```

This lets Terraform's Google provider authenticate using your own credentials, no service account key file needed for a personal sandbox.

---

## Step 4: Unzip the codebase

```bash
unzip pipeman-app.zip && cd pipeman-app
```

A `.gitignore` is included and already excludes `.env`, `venv/`, and Terraform's state files. If you plan to `git init` at any point (Step 11 covers this properly), do it only after this `.gitignore` is in place, never before, since anything committed once stays in git history even after you add `.gitignore` later.

---

## Step 5: Provision infrastructure with Terraform

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and set `project_id` to your sandbox project.

```bash
terraform init
terraform validate
terraform plan
```

Read the plan, it should show roughly 15 resources to create: enabled APIs, a service account with 3 IAM bindings, a Cloud Storage bucket, a Cloud SQL instance/database/user, a Secret Manager secret, an Artifact Registry repo, and the Vertex AI Vector Search index/endpoint/deployment.

```bash
terraform apply
```

This will take a while, the Vector Search index and its deployment are the slowest parts, often 20-45 minutes. That's normal for this service, not a stuck command.

> **Before this step**, read `terraform/README.md`'s note on the `google_vertex_ai_index_endpoint_deployed_index` resource. It's a newer part of the provider and has shifted between versions; if it errors, the guide there shows a one-line `gcloud` fallback for just that resource, everything else in Terraform still applies normally.

---

## Step 6: Capture the Terraform outputs into `.env`

```bash
cd ..  # back to the pipeman-app root
cp .env.example .env
```

```bash
terraform -chdir=terraform output cloudsql_connection_name
terraform -chdir=terraform output -raw db_password
terraform -chdir=terraform output vector_search_index_id
terraform -chdir=terraform output vector_search_endpoint_id
```

Copy each value into the matching field in `.env`:

- `CLOUDSQL_INSTANCE_CONNECTION_NAME`
- `CLOUDSQL_DB_PASSWORD`
- `VECTOR_SEARCH_INDEX_ID`
- `VECTOR_SEARCH_ENDPOINT_ID`
- `GCP_PROJECT_ID` and `GCP_REGION` (your own values, matching `terraform.tfvars`)

`VECTOR_SEARCH_DEPLOYED_INDEX_ID` is already correct in `.env.example` (`pipeman_deployed_index`), matching the ID set in `terraform/main.tf`, no need to change it unless you edited that value.

---

## Step 7: Install dependencies and add your sample data

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

1. Drop a few public PDFs into `sample_data/pdfs/` (e.g. a published agency policy document).
2. Drop one or two public Excel workbooks into `sample_data/excel/`.
3. Edit `sample_data/manifest.json`: for each Excel sheet, classify it as `"reference"` (with a `key_column`) or `"analytical"` (with a `table_name`). This classification is deliberately manual, per the Design Document, getting it wrong routes questions down the wrong path.

---

## Step 8: Run the ingestion pipeline

```bash
python -m ingestion.run_ingestion
```

What this actually does, matching the Data Flow Diagram's Part 1/2 split in reverse (building the store the retrieval pipeline will read from):

- For each PDF, `ingestion/parse_pdf.py` walks the document, detects headings heuristically, and builds a `hierarchy_path` per chunk (e.g. `"DoD > DLA > Section 2"`).
- Each chunk is embedded via Vertex AI's `text-embedding-005`. The embedding vector is upserted into the Vertex AI Vector Search index (tagged with `record_type=chunk` and an `access_role` restrict); the chunk's text and citation metadata are written to Cloud SQL, keyed by the same `datapoint_id`.
- For each Excel sheet, `ingestion/parse_excel.py` either loads it as-is into a plain analytical table in Cloud SQL (queried later with SQL, never embedded) or builds structured `reference_records`, written to Cloud SQL with a flattened, embedded text representation upserted to Vector Search (tagged `record_type=reference`) for the search fallback.

> For messier or scanned real-world documents (the eventual DGEE catalog), replace the heuristic heading detector in `parse_pdf.py` with a call to Document AI's Layout Parser, it reads visual structure rather than guessing from text patterns. The rest of the pipeline does not need to change.

> New data upserted to Vector Search can take a few minutes to become searchable (STREAM_UPDATE propagation). If your first query right after ingestion comes back empty, wait a minute and try again before assuming something is broken.

---

## Step 9: Run and test the retrieval pipeline

```bash
uvicorn backend.main:app --reload --port 8080
```

In a second terminal:

```bash
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What does the document say about inspection frequency?"}'
```

This exercises the full Sequence Diagram for one request: the combined query-rewrite-and-classify call (`backend/query_rewriter.py`), Vector Search retrieval with the confidence gate (`backend/retrieval.py`), grounded generation (`backend/generation.py`), and confidence scoring (`backend/confidence.py`). Try a few different question types, a direct lookup, a comparison question, and (if you classified a reference sheet) a lookup question, to see the `intent` and `model_used` fields change in the response.

---

## Step 10: Test with the web interface

```bash
cd frontend
python -m http.server 5500
```

Open `http://localhost:5500` in a browser.

The role dropdown lets you simulate different access levels against the `access_role` restrict set during ingestion, useful for confirming retrieval-time filtering actually works before you have a real auth system to test against. The response panel under each answer shows confidence, intent, which model answered, and the rewritten query, so you can see the pipeline's internal decisions, not just its final text.

---

## Step 11: Set up CI/CD (Cloud Build)

**Before running any `git` command**, confirm `.gitignore` exists at the root of `pipeman-app/` (it ships in the codebase) and actually excludes `.env`, `venv/`, and `terraform/terraform.tfstate*`:

```bash
cat .gitignore
```

If you already ran `git init`/`git add`/`git commit` before reading this, **do not just add `.gitignore` now and move on**, files already committed stay in git's history even after you `.gitignore` them going forward. Check what's already tracked:

```bash
git ls-files | grep -E "^\.env$|^venv/|terraform\.tfstate"
```

If anything shows up, this repo's history already contains secrets. For a personal sandbox with no other collaborators, the cleanest fix is a full reset rather than surgical history rewriting:

```bash
rm -rf .git
git init
git add .
git status   # confirm .env, venv/, terraform.tfstate are NOT listed
git commit -m "Initial Pipeman sandbox"
```

**Then, regardless of whether you can prove anything reached GitHub**, treat any credential that was ever committed as compromised and rotate it, this is not optional:

```bash
gcloud sql users set-password pipeman_app \
  --instance=pipeman-sandbox-db \
  --password='NEW_PASSWORD_HERE'
```

Update `.env` locally with the new password (it will not be committed now that `.gitignore` is respected from the first commit).

**Now proceed with GitHub:**

```bash
git remote add origin https://github.com/YOUR_GITHUB_USER/YOUR_REPO.git
git branch -M main
git push -u origin main
```

Then connect the repo and create the trigger:

```bash
gcloud builds triggers create github \
  --repo-name=YOUR_REPO --repo-owner=YOUR_GITHUB_USER \
  --branch-pattern="^main$" --build-config=cloudbuild.yaml
```

`cloudbuild.yaml` (already in the codebase) builds the container, pushes it to Artifact Registry (which scans it for known vulnerabilities automatically), and deploys to a staging Cloud Run service, private by default (`--no-allow-unauthenticated`). Promotion to a production service is a deliberate separate, manual step, not part of the automatic trigger, matching the staged-rollout practice from the Design Document's Operational Model section.

**Manual deploy**, if you want to skip straight to Cloud Run once:

```bash
gcloud run deploy pipeman-backend \
  --source . --region us-central1 \
  --no-allow-unauthenticated \
  --set-cloudsql-instances=$(terraform -chdir=terraform output -raw cloudsql_connection_name) \
  --update-secrets=CLOUDSQL_DB_PASSWORD=pipeman-sandbox-db-password:latest
```

---

## Step 12: Manage cost (personal account)

Vertex AI Vector Search's deployed index is the main ongoing cost here, it bills for always-on serving capacity, not per query, so it keeps charging even while you're not actively testing.

- **Set a budget alert immediately**: Billing > Budgets & alerts, alert at $10, $25, $50.
- **Confirm what's running**:
  ```bash
  terraform -chdir=terraform state list
  ```
- **Tear everything down the moment you've confirmed it works**:
  ```bash
  terraform -chdir=terraform destroy
  ```
  This removes the Vector Search deployment, the Cloud SQL instance, and everything else Terraform created, the cleanest way to guarantee nothing keeps billing between sessions.
- **To pick back up later**: `terraform apply` again with the same `terraform.tfvars`, then re-run Step 6 (outputs will have new values) and Step 8 (re-ingest, since destroying Cloud SQL and Vector Search removed your data).

---

## Step 13: What changes for the enterprise deployment

This sandbox is architecturally identical to the production design, not a simplified version of it, the same Vertex AI Vector Search index type, the same Cloud SQL metadata schema, the same code. Moving to work changes configuration, data, and a few hardening details, not the architecture:

- **PDF parsing**: swap the heuristic heading detector for Document AI's Layout Parser for the real DGEE catalog's messier formatting.
- **Auth**: `user_role` currently comes from the request body for sandbox testing; in production it comes from validating the existing web app's session token (see the Infrastructure Requirements document).
- **Vector Search endpoint**: switch `public_endpoint_enabled` to a private, VPC-based endpoint in `terraform/main.tf` for the IL5 boundary, this sandbox uses a public endpoint for simplicity.
- **Terraform state and environments**: the sandbox runs Terraform with local state and a single environment; at work, add a remote state backend (a Cloud Storage bucket) and separate `dev`/`staging`/`prod` variable files.
- **Everything else**: the chunking logic, the two-tier reference lookup, the classifier-router-generator flow, the confidence gate, and the Vector Search restricts-based access control all carry over unchanged.

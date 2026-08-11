# Pipeman

A working implementation of the Pipeman ingestion and retrieval pipelines,
built to match the Pipeman Design Document component-for-component,
including Vertex AI Vector Search as the vector store (the same service
used in the enterprise design, no sandbox substitution).

## Structure

```
terraform/     Infrastructure as code: APIs, Cloud SQL, Vector Search, etc.
ingestion/     Offline pipeline: parse PDFs/Excel, chunk, embed, upload
backend/       Online pipeline: FastAPI app implementing the retrieval pipeline
frontend/      Static HTML/JS test console (no build step required)
sample_data/   Put your own public PDFs/Excel here + manifest.json
```

## Security

`.gitignore` is included and excludes `.env`, `venv/`, and Terraform state files, all of which can contain real credentials. Never remove `.env` from `.gitignore`. If you ever find a credential was committed to git history, rotate it immediately, don't just remove it going forward, files committed once remain in history even after being added to `.gitignore` later.

## Quick start

1. Provision infrastructure: see `terraform/README.md`
2. `cp .env.example .env` and fill in values from `terraform output`
3. `pip install -r requirements.txt`
4. Put a few public PDFs in `sample_data/pdfs/` and Excel files in `sample_data/excel/`
5. Fill in `sample_data/manifest.json` classifying each Excel sheet
6. Run ingestion: `python -m ingestion.run_ingestion`
7. Start the backend: `uvicorn backend.main:app --reload --port 8080`
8. Open `frontend/index.html` (or serve it with `python -m http.server 5500`
   from the `frontend/` folder) and start asking questions

Full step-by-step walkthrough is in the Execution Guide document.

"""
Ingestion pipeline entrypoint (runs offline).

Usage:
    python -m ingestion.run_ingestion --pdf-dir sample_data/pdfs \
        --excel-dir sample_data/excel --manifest sample_data/manifest.json

This walks every PDF in --pdf-dir (hierarchical chunk + embed + upload),
and every Excel workbook in --excel-dir (classified per sheet via the
manifest into analytical or reference handling, per the Design Document).
"""
import argparse
import json
import os

from ingestion.config import config
from ingestion.parse_pdf import build_hierarchical_chunks
from ingestion.parse_excel import (
    load_analytical_sheet,
    load_reference_sheet,
    suggest_classification,
)
from ingestion.embed_and_upload import (
    ensure_schema,
    upload_chunks,
    upload_reference_records,
    upload_analytical_dataframe,
)
import pandas as pd


def ingest_pdfs(pdf_dir: str):
    if not os.path.isdir(pdf_dir):
        print(f"No PDF directory at {pdf_dir}, skipping.")
        return
    for filename in sorted(os.listdir(pdf_dir)):
        if not filename.lower().endswith(".pdf"):
            continue
        path = os.path.join(pdf_dir, filename)
        print(f"Chunking {filename} ...")
        chunks = build_hierarchical_chunks(path, source_document=filename)
        print(f"  {len(chunks)} chunks produced, embedding and uploading ...")
        upload_chunks(chunks)


def ingest_excel(excel_dir: str, manifest_path: str | None):
    if not os.path.isdir(excel_dir):
        print(f"No Excel directory at {excel_dir}, skipping.")
        return

    manifest = {}
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            raw = json.load(f)
        # manifest.json format: {"file.xlsx::Sheet1": {"type": "reference", "key_column": "Code"}}
        manifest = raw

    for filename in sorted(os.listdir(excel_dir)):
        if not filename.lower().endswith((".xlsx", ".xls")):
            continue
        path = os.path.join(excel_dir, filename)
        xls = pd.ExcelFile(path)
        for sheet_name in xls.sheet_names:
            manifest_key = f"{filename}::{sheet_name}"
            entry = manifest.get(manifest_key)

            if entry is None:
                df_preview = pd.read_excel(path, sheet_name=sheet_name, nrows=50)
                suggestion = suggest_classification(df_preview)
                print(
                    f"WARNING: no manifest entry for {manifest_key}. "
                    f"Skipping ingestion. Heuristic suggests '{suggestion}'. "
                    f"Add an entry to your manifest and rerun."
                )
                continue

            sheet_type = entry["type"]
            print(f"Ingesting {manifest_key} as '{sheet_type}' ...")

            if sheet_type == "analytical":
                df = load_analytical_sheet(path, sheet_name)
                table_name = entry.get("table_name", f"{filename}_{sheet_name}".replace(".", "_"))
                upload_analytical_dataframe(df, table_name)

            elif sheet_type == "reference":
                key_column = entry["key_column"]
                records = load_reference_sheet(path, sheet_name, key_column)
                upload_reference_records(records)

            else:
                print(f"  Unknown type '{sheet_type}' for {manifest_key}, skipping.")


def main():
    parser = argparse.ArgumentParser(description="Pipeman ingestion pipeline")
    parser.add_argument("--pdf-dir", default="sample_data/pdfs")
    parser.add_argument("--excel-dir", default="sample_data/excel")
    parser.add_argument("--manifest", default="sample_data/manifest.json")
    args = parser.parse_args()

    print(f"Connecting to Cloud SQL instance {config.CLOUDSQL_INSTANCE_CONNECTION_NAME} ...")
    ensure_schema()

    ingest_pdfs(args.pdf_dir)
    ingest_excel(args.excel_dir, args.manifest)

    print("Ingestion complete.")


if __name__ == "__main__":
    main()

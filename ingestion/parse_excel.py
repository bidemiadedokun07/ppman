"""
Excel parsing for both data categories described in the Pipeman Design
Document (Section 2): analytical data (needs computation/aggregation, goes
to a queryable table) and reference/lookup data (direct record retrieval,
gets a structured record plus a flattened text representation for
semantic-search fallback).

Classification of each sheet is explicit, not guessed, via a manifest you
provide (see sample_manifest below), because getting this wrong routes
questions down the wrong path (see Design Document, "Excel data is routed
by content type, not assumed to be one thing"). A lightweight heuristic is
provided only as a fallback suggestion when a sheet is not in the manifest.
"""
from dataclasses import dataclass
import pandas as pd

# Example manifest entry format. In practice, load this from a small
# YAML/JSON file checked into your ingestion config, one entry per
# workbook + sheet.
SAMPLE_MANIFEST = {
    ("public_reference_example.xlsx", "Sheet1"): "reference",
    ("public_analytics_example.xlsx", "Sheet1"): "analytical",
}


@dataclass
class ReferenceRecord:
    row_id: str
    fields: dict
    flattened_text: str
    source_workbook: str
    source_sheet: str


def suggest_classification(df: pd.DataFrame) -> str:
    """
    Fallback heuristic only, used when a sheet has no manifest entry.
    Mostly-numeric columns with few unique text columns suggest analytical
    data; mostly-text/categorical columns with an identifiable key column
    suggest reference/lookup data. Always confirm manually before ingesting
    real DGEE content.
    """
    numeric_ratio = df.select_dtypes(include="number").shape[1] / max(df.shape[1], 1)
    return "analytical" if numeric_ratio > 0.5 else "reference"


def load_analytical_sheet(path: str, sheet_name: str) -> pd.DataFrame:
    """
    Analytical sheets are loaded as-is and handed to the BigQuery loader
    unchanged; no chunking or embedding, this data is queried with SQL.
    """
    return pd.read_excel(path, sheet_name=sheet_name)


def load_reference_sheet(path: str, sheet_name: str, key_column: str) -> list[ReferenceRecord]:
    """
    Reference/lookup sheets become structured records (for exact/fuzzy key
    match) plus a flattened text string per row (for the hybrid-search
    fallback described in the Design Document, Section 2).
    """
    df = pd.read_excel(path, sheet_name=sheet_name)
    if key_column not in df.columns:
        raise ValueError(
            f"key_column '{key_column}' not found in {path}:{sheet_name}. "
            f"Available columns: {list(df.columns)}"
        )

    records: list[ReferenceRecord] = []
    for _, row in df.iterrows():
        fields = {col: ("" if pd.isna(row[col]) else row[col]) for col in df.columns}
        flattened = ", ".join(f"{col}: {val}" for col, val in fields.items() if val != "")
        records.append(
            ReferenceRecord(
                row_id=str(fields[key_column]),
                fields=fields,
                flattened_text=flattened,
                source_workbook=path,
                source_sheet=sheet_name,
            )
        )
    return records

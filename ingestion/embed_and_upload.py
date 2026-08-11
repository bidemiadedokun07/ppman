"""
Generates embeddings via Vertex AI and writes them to Vertex AI Vector
Search (the managed, always-on index), matching the enterprise design
exactly. Full chunk/record text and metadata are written to Cloud SQL for
PostgreSQL, keyed by the same datapoint_id used in the Vector Search
index, so a nearest-neighbor query result can be joined back to its full
content.

Note: the google-cloud-aiplatform SDK's exact method signatures for
upsert_datapoints have shifted between versions. If a call here errors,
check `pip show google-cloud-aiplatform` and confirm the call shape
against the MatchingEngineIndex reference for your installed version.
"""
import json
import time
import uuid
from google.cloud.sql.connector import Connector
import pg8000
from google.cloud import aiplatform
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable, DeadlineExceeded
import vertexai
from vertexai.language_models import TextEmbeddingModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ingestion.config import config
from ingestion.parse_pdf import Chunk
from ingestion.parse_excel import ReferenceRecord

vertexai.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
_embedding_model = TextEmbeddingModel.from_pretrained(config.MODEL_EMBEDDING)

aiplatform.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
_index = aiplatform.MatchingEngineIndex(config.VECTOR_SEARCH_INDEX_ID)

_connector = Connector()


def get_connection():
    return _connector.connect(
        config.CLOUDSQL_INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=config.CLOUDSQL_DB_USER,
        password=config.CLOUDSQL_DB_PASSWORD,
        db=config.CLOUDSQL_DB_NAME,
    )


def ensure_schema():
    """Creates the metadata tables if they do not exist yet. No vector
    columns here, embeddings live in Vertex AI Vector Search; these tables
    hold the text and metadata a datapoint_id resolves to."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            datapoint_id TEXT PRIMARY KEY,
            source_document TEXT NOT NULL,
            hierarchy_path TEXT NOT NULL,
            page_number INT,
            chunk_index INT,
            chunk_text TEXT NOT NULL,
            version_id TEXT DEFAULT 'v1',
            is_current BOOLEAN DEFAULT TRUE,
            access_role TEXT DEFAULT 'public'
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reference_records (
            datapoint_id TEXT PRIMARY KEY,
            row_id TEXT NOT NULL,
            source_workbook TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            fields_json JSONB NOT NULL,
            flattened_text TEXT NOT NULL,
            access_role TEXT DEFAULT 'public'
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


@retry(
    retry=retry_if_exception_type((ResourceExhausted, InternalServerError, ServiceUnavailable, DeadlineExceeded)),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(6),
)
def _embed_batch(texts: list[str]) -> list[list[float]]:
    embeddings = _embedding_model.get_embeddings(texts)
    return [e.values for e in embeddings]


def _upsert_vectors(datapoints: list[dict]):
    """
    datapoints: list of {"datapoint_id": str, "feature_vector": list[float],
    "restricts": [{"namespace": str, "allow_list": list[str]}]}

    Restricts are how access control and record-type filtering (chunk vs.
    reference) are enforced at query time by Vector Search itself, not by
    a downstream SQL WHERE clause.
    """
    _index.upsert_datapoints(datapoints=datapoints)


def upload_chunks(chunks: list[Chunk], access_role: str = "public", version_id: str = "v1"):
    if not chunks:
        return
    conn = get_connection()
    cur = conn.cursor()
    batch_size = 5  # small, to stay under new-project default quota
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectors = _embed_batch([c.text for c in batch])
        time.sleep(1)  # small pause between batches to stay under per-minute quota
        datapoints = []
        for chunk, vector in zip(batch, vectors):
            dp_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO document_chunks
                    (datapoint_id, source_document, hierarchy_path, page_number,
                     chunk_index, chunk_text, version_id, access_role)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dp_id, chunk.source_document, chunk.hierarchy_path, chunk.page_number,
                    chunk.chunk_index, chunk.text, version_id, access_role,
                ),
            )
            datapoints.append({
                "datapoint_id": dp_id,
                "feature_vector": vector,
                "restricts": [
                    {"namespace": "record_type", "allow_list": ["chunk"]},
                    {"namespace": "access_role", "allow_list": [access_role]},
                ],
            })
        _upsert_vectors(datapoints)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Uploaded {len(chunks)} chunks (Cloud SQL metadata + Vector Search embeddings).")


def upload_reference_records(records: list[ReferenceRecord], access_role: str = "public"):
    if not records:
        return
    conn = get_connection()
    cur = conn.cursor()
    batch_size = 5  # small, to stay under new-project default quota
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        vectors = _embed_batch([r.flattened_text for r in batch])
        time.sleep(1)  # small pause between batches to stay under per-minute quota
        datapoints = []
        for record, vector in zip(batch, vectors):
            dp_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO reference_records
                    (datapoint_id, row_id, source_workbook, source_sheet,
                     fields_json, flattened_text, access_role)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dp_id, record.row_id, record.source_workbook, record.source_sheet,
                    json.dumps(record.fields), record.flattened_text, access_role,
                ),
            )
            datapoints.append({
                "datapoint_id": dp_id,
                "feature_vector": vector,
                "restricts": [
                    {"namespace": "record_type", "allow_list": ["reference"]},
                    {"namespace": "access_role", "allow_list": [access_role]},
                ],
            })
        _upsert_vectors(datapoints)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Uploaded {len(records)} reference records (Cloud SQL metadata + Vector Search embeddings).")


def upload_analytical_dataframe(df, table_name: str):
    """
    Analytical data goes to its own plain table (no embedding at all);
    this data is queried with SQL, never vector similarity.
    """
    import pandas as pd

    conn = get_connection()
    cols_def = ", ".join(f'"{c}" TEXT' for c in df.columns)
    cur = conn.cursor()
    cur.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols_def});')
    for _, row in df.iterrows():
        placeholders = ", ".join(["%s"] * len(df.columns))
        col_names = ", ".join(f'"{c}"' for c in df.columns)
        values = [None if pd.isna(v) else str(v) for v in row.tolist()]
        cur.execute(f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})', values)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Uploaded {len(df)} analytical rows to {table_name}.")

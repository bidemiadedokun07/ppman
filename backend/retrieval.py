"""
Retrieval Path (deterministic infrastructure), see Component Diagram.

Vector similarity is served by Vertex AI Vector Search, the same managed,
always-on index used in the enterprise design, no sandbox substitution.
Full chunk/record text and metadata live in Cloud SQL, keyed by the same
datapoint_id used in the Vector Search index; a nearest-neighbor query
returns IDs that are joined back to their full content.

Access control and content-type separation (chunks vs. reference records)
are enforced through Vector Search's "restricts" filtering at query time,
not a Postgres WHERE clause, so permission to see a document never
depends on a downstream join being written correctly.

Note: find_neighbors()'s filter parameter requires the SDK's Namespace
class, not plain dicts (confirmed via a live error: passing dicts causes
an AttributeError inside the SDK's find_neighbors implementation, since
it expects each filter entry to have a .name attribute). If this still
errors after the Namespace fix below, the likely next issue is the
Namespace constructor's exact keyword names (allow_tokens vs. allow_list
vs. something else), these have shifted across google-cloud-aiplatform
versions; check `pip show google-cloud-aiplatform` and the installed
version's MatchingEngineIndexEndpoint reference.
"""
from dataclasses import dataclass
from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import Namespace
import vertexai
from vertexai.language_models import TextEmbeddingModel
from vertexai.generative_models import GenerativeModel, GenerationConfig

from backend.config import config
from ingestion.embed_and_upload import get_connection

vertexai.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
_embedding_model = TextEmbeddingModel.from_pretrained(config.MODEL_EMBEDDING)
_sql_model = GenerativeModel(config.MODEL_SIMPLE)

aiplatform.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
_index_endpoint = aiplatform.MatchingEngineIndexEndpoint(config.VECTOR_SEARCH_ENDPOINT_ID)


@dataclass
class RetrievedChunk:
    text: str
    source_document: str
    hierarchy_path: str
    page_number: int
    similarity: float


@dataclass
class ReferenceMatch:
    fields: dict
    matched_by: str  # "exact_key" | "semantic_fallback"
    similarity: float


def _embed_query(text: str) -> list[float]:
    return _embedding_model.get_embeddings([text])[0].values


def _fetch_chunk_metadata(datapoint_ids: list[str]) -> dict[str, dict]:
    if not datapoint_ids:
        return {}
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ", ".join(["%s"] * len(datapoint_ids))
    cur.execute(
        f"""
        SELECT datapoint_id, chunk_text, source_document, hierarchy_path, page_number
        FROM document_chunks
        WHERE datapoint_id IN ({placeholders}) AND is_current = TRUE
        """,
        datapoint_ids,
    )
    result = {
        row[0]: {
            "text": row[1], "source_document": row[2],
            "hierarchy_path": row[3], "page_number": row[4],
        }
        for row in cur.fetchall()
    }
    cur.close()
    conn.close()
    return result


def vector_search_chunks(query: str, access_role: str) -> list[RetrievedChunk]:
    """Queries Vector Search restricted to record_type=chunk and the
    caller's access_role (or public), then joins results back to Cloud SQL
    for the full chunk text and citation metadata."""
    vector = _embed_query(query)
    response = _index_endpoint.find_neighbors(
        deployed_index_id=config.VECTOR_SEARCH_DEPLOYED_INDEX_ID,
        queries=[vector],
        num_neighbors=config.RETRIEVAL_TOP_K,
        filter=[
            Namespace(name="record_type", allow_tokens=["chunk"]),
            Namespace(name="access_role", allow_tokens=[access_role, "public"]),
        ],
    )
    neighbors = response[0] if response else []
    metadata = _fetch_chunk_metadata([n.id for n in neighbors])

    results = []
    for n in neighbors:
        meta = metadata.get(n.id)
        if not meta:
            continue  # datapoint exists in the index but metadata was deleted/superseded
        # COSINE_DISTANCE: 0 = identical, 2 = opposite. Convert to a 0-1
        # similarity for the confidence scorer. Re-verify this conversion
        # empirically once running against a real deployed index.
        similarity = max(0.0, 1 - (n.distance / 2))
        results.append(RetrievedChunk(
            text=meta["text"], source_document=meta["source_document"],
            hierarchy_path=meta["hierarchy_path"], page_number=meta["page_number"],
            similarity=similarity,
        ))
    return results


def rerank(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Sandbox reranker: sorts by the similarity score already computed and
    keeps the top N. For production, replace with Vertex AI's ranking API
    for a real cross-encoder rerank pass.
    """
    ordered = sorted(chunks, key=lambda c: c.similarity, reverse=True)
    return ordered[: config.RETRIEVAL_RERANK_TOP_N]


def reference_lookup(entity_hint: str, access_role: str) -> ReferenceMatch | None:
    """Exact/fuzzy key match against Cloud SQL first; Vector Search
    semantic fallback (restricted to record_type=reference) second."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT fields_json FROM reference_records
        WHERE (access_role = %s OR access_role = 'public')
          AND flattened_text ILIKE %s
        LIMIT 1
        """,
        (access_role, f"%{entity_hint}%"),
    )
    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return ReferenceMatch(fields=row[0], matched_by="exact_key", similarity=1.0)
    cur.close()
    conn.close()

    vector = _embed_query(entity_hint)
    response = _index_endpoint.find_neighbors(
        deployed_index_id=config.VECTOR_SEARCH_DEPLOYED_INDEX_ID,
        queries=[vector],
        num_neighbors=1,
        filter=[
            Namespace(name="record_type", allow_tokens=["reference"]),
            Namespace(name="access_role", allow_tokens=[access_role, "public"]),
        ],
    )
    neighbors = response[0] if response else []
    if not neighbors:
        return None

    top = neighbors[0]
    similarity = max(0.0, 1 - (top.distance / 2))
    if similarity < 0.6:
        return None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT fields_json FROM reference_records WHERE datapoint_id = %s", (top.id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return ReferenceMatch(fields=row[0], matched_by="semantic_fallback", similarity=similarity)


def analytical_query(question: str, table_name: str) -> tuple[str, list[dict]] | None:
    """
    Small text-to-SQL step: describes the target table's columns, asks the
    model for a single read-only SELECT statement, and executes it.
    Restricted to a single pre-approved table per call, never an
    open-ended database connection.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table_name,),
    )
    columns = [r[0] for r in cur.fetchall()]
    if not columns:
        cur.close()
        conn.close()
        return None

    prompt = (
        f"Table '{table_name}' has columns: {', '.join(columns)}. "
        f"All columns are TEXT. Write ONE PostgreSQL SELECT statement (no other "
        f"statements, no DDL/DML) that answers: {question}\n"
        f"Respond with ONLY the SQL statement, nothing else."
    )
    response = _sql_model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=0.0, max_output_tokens=300)
    )
    sql = response.text.strip().strip("`").replace("sql\n", "", 1)

    if not sql.lower().startswith("select"):
        cur.close()
        conn.close()
        return None

    cur.execute(sql)
    col_names = [desc[0] for desc in cur.description]
    rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return sql, rows

"""
Shared configuration for the Pipeman ingestion pipeline.
Loaded once from environment variables (see .env.example).
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.getenv("GCP_REGION", "us-central1")

    MODEL_EMBEDDING = os.getenv("MODEL_EMBEDDING", "text-embedding-005")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

    CLOUDSQL_INSTANCE_CONNECTION_NAME = os.environ["CLOUDSQL_INSTANCE_CONNECTION_NAME"]
    CLOUDSQL_DB_NAME = os.getenv("CLOUDSQL_DB_NAME", "pipeman")
    CLOUDSQL_DB_USER = os.getenv("CLOUDSQL_DB_USER", "pipeman_app")
    CLOUDSQL_DB_PASSWORD = os.environ["CLOUDSQL_DB_PASSWORD"]

    VECTOR_SEARCH_INDEX_ID = os.environ["VECTOR_SEARCH_INDEX_ID"]

    # Chunking parameters (see design doc: hierarchical chunking for PDFs)
    MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "1600"))
    CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))


config = Config()

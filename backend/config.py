"""
Shared configuration for the Pipeman retrieval pipeline (backend API).
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    GCP_REGION = os.getenv("GCP_REGION", "us-central1")

    MODEL_CLASSIFIER = os.getenv("MODEL_CLASSIFIER", "gemini-2.5-flash-lite")
    MODEL_SIMPLE = os.getenv("MODEL_SIMPLE", "gemini-2.5-flash")
    MODEL_COMPLEX = os.getenv("MODEL_COMPLEX", "gemini-2.5-pro")
    MODEL_EMBEDDING = os.getenv("MODEL_EMBEDDING", "text-embedding-005")

    CLOUDSQL_INSTANCE_CONNECTION_NAME = os.environ["CLOUDSQL_INSTANCE_CONNECTION_NAME"]
    CLOUDSQL_DB_NAME = os.getenv("CLOUDSQL_DB_NAME", "pipeman")
    CLOUDSQL_DB_USER = os.getenv("CLOUDSQL_DB_USER", "pipeman_app")
    CLOUDSQL_DB_PASSWORD = os.environ["CLOUDSQL_DB_PASSWORD"]

    RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "8"))
    RETRIEVAL_RERANK_TOP_N = int(os.getenv("RETRIEVAL_RERANK_TOP_N", "4"))
    CONFIDENCE_HIGH_THRESHOLD = float(os.getenv("CONFIDENCE_HIGH_THRESHOLD", "0.80"))
    CONFIDENCE_MEDIUM_THRESHOLD = float(os.getenv("CONFIDENCE_MEDIUM_THRESHOLD", "0.55"))

    VECTOR_SEARCH_INDEX_ID = os.environ["VECTOR_SEARCH_INDEX_ID"]
    VECTOR_SEARCH_ENDPOINT_ID = os.environ["VECTOR_SEARCH_ENDPOINT_ID"]
    VECTOR_SEARCH_DEPLOYED_INDEX_ID = os.environ["VECTOR_SEARCH_DEPLOYED_INDEX_ID"]

    ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5500").split(",")]


config = Config()

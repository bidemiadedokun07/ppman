"""
Generation Path (probabilistic flows): model routing and grounded
generation. Never generates from the model's general knowledge, per the
Design Document's core requirement, "answer only from approved documents."
"""
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

from backend.config import config
from backend.retrieval import RetrievedChunk

vertexai.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)

_GROUNDED_SYSTEM_PROMPT = """You are Pipeman, a compliance knowledge assistant.
Answer ONLY using the provided context below. Every claim in your answer must
be traceable to the context. If the context does not contain the answer, say
exactly: "I couldn't find this information in the approved documentation."
Never use outside knowledge. Never guess. Cite which source each part of your
answer came from using the [n] markers shown in the context.
"""


def _model_for_intent(intent: str) -> GenerativeModel:
    name = config.MODEL_COMPLEX if intent == "complex" else config.MODEL_SIMPLE
    return GenerativeModel(name), name


def generate_from_chunks(question: str, chunks: list[RetrievedChunk], intent: str) -> tuple[str, str]:
    if not chunks:
        return "I couldn't find this information in the approved documentation.", "none"

    context_blocks = "\n\n".join(
        f"[{i+1}] (Source: {c.source_document} | {c.hierarchy_path} | page {c.page_number})\n{c.text}"
        for i, c in enumerate(chunks)
    )
    prompt = f"{_GROUNDED_SYSTEM_PROMPT}\n\nContext:\n{context_blocks}\n\nQuestion: {question}\n\nAnswer:"

    model, model_name = _model_for_intent(intent)
    response = model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=0.1, max_output_tokens=1024)
    )
    return response.text.strip(), model_name


def format_structured_result(question: str, sql: str, rows: list[dict]) -> tuple[str, str]:
    """Narrates a structured query result; never recalculates the numbers itself."""
    model_name = config.MODEL_SIMPLE
    model = GenerativeModel(model_name)
    prompt = (
        f"A database query was run to answer this question: {question}\n"
        f"Query: {sql}\nResult rows (already correct, do not recompute): {rows}\n\n"
        f"Write a short, direct natural-language answer using only these rows. "
        f"If rows is empty, say the data was not found, do not guess a value."
    )
    response = model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=0.0, max_output_tokens=400)
    )
    return response.text.strip(), model_name


def format_reference_result(question: str, fields: dict) -> tuple[str, str]:
    model_name = config.MODEL_SIMPLE
    model = GenerativeModel(model_name)
    prompt = (
        f"Question: {question}\nMatched record (already correct, do not alter values): {fields}\n\n"
        f"Answer the question directly using only this record's fields."
    )
    response = model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=0.0, max_output_tokens=300)
    )
    return response.text.strip(), model_name

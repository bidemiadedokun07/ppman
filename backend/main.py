"""
Pipeman retrieval pipeline API (runs at query time).

This implements the Sequence Diagram end to end for one request:
rewrite+classify -> route -> retrieve/lookup/query -> generate ->
confidence -> respond. Run locally with:

    uvicorn backend.main:app --reload --port 8080

Then point the test frontend (frontend/index.html) at http://localhost:8080.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import config
from backend.models import QueryRequest, QueryResponse, Citation
from backend.query_rewriter import rewrite_and_classify
from backend.retrieval import vector_search_chunks, rerank, reference_lookup, analytical_query
from backend.generation import generate_from_chunks, format_structured_result, format_reference_result
from backend.confidence import (
    score_from_chunks,
    score_from_reference_match,
    score_from_structured_result,
    confidence_label,
)

app = FastAPI(title="Pipeman Retrieval Pipeline (Sandbox)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure which analytical table an "analytics" question queries against.
# In the sandbox this is a single table for simplicity; production routing
# by topic/table is a Section 6 upgrade in the Execution Guide.
ANALYTICAL_TABLE_NAME = "inspections_analytical"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    # Step 1: combined query rewriting + classification (one Flash-Lite call)
    rewritten_query, intent = rewrite_and_classify(request.question, request.conversation_history)

    # Step 2-3: route to the right retrieval mechanism and generation path
    if intent == "reference":
        match = reference_lookup(rewritten_query, request.user_role)
        if match is None:
            return QueryResponse(
                answer="I couldn't find this information in the approved documentation.",
                citations=[],
                confidence="low",
                confidence_score=0.0,
                intent=intent,
                model_used="none",
                rewritten_query=rewritten_query,
            )
        answer, model_used = format_reference_result(rewritten_query, match.fields)
        score = score_from_reference_match(match.similarity, match.matched_by)
        return QueryResponse(
            answer=answer,
            citations=[Citation(source_document="reference_records", hierarchy_path=None, page_number=None)],
            confidence=confidence_label(score),
            confidence_score=round(score, 3),
            intent=intent,
            model_used=model_used,
            rewritten_query=rewritten_query,
        )

    if intent == "analytics":
        result = analytical_query(rewritten_query, ANALYTICAL_TABLE_NAME)
        if result is None:
            return QueryResponse(
                answer="I couldn't find this information in the approved documentation.",
                citations=[],
                confidence="low",
                confidence_score=0.0,
                intent=intent,
                model_used="none",
                rewritten_query=rewritten_query,
            )
        sql, rows = result
        answer, model_used = format_structured_result(rewritten_query, sql, rows)
        score = score_from_structured_result(rows)
        return QueryResponse(
            answer=answer,
            citations=[Citation(source_document=ANALYTICAL_TABLE_NAME, hierarchy_path=None, page_number=None)],
            confidence=confidence_label(score),
            confidence_score=round(score, 3),
            intent=intent,
            model_used=model_used,
            rewritten_query=rewritten_query,
        )

    # "simple" or "complex": hybrid retrieval + rerank + grounded generation
    candidates = vector_search_chunks(rewritten_query, request.user_role)
    top_chunks = rerank(candidates)

    # Hard confidence gate BEFORE generation: never ask the model to answer
    # from weak or absent retrieval, per the Design Document's architectural
    # gate requirement.
    pre_score = score_from_chunks(top_chunks)
    if pre_score < config.CONFIDENCE_MEDIUM_THRESHOLD:
        return QueryResponse(
            answer="I couldn't find this information in the approved documentation.",
            citations=[],
            confidence="low",
            confidence_score=round(pre_score, 3),
            intent=intent,
            model_used="none",
            rewritten_query=rewritten_query,
        )

    answer, model_used = generate_from_chunks(rewritten_query, top_chunks, intent)
    citations = [
        Citation(source_document=c.source_document, hierarchy_path=c.hierarchy_path, page_number=c.page_number)
        for c in top_chunks
    ]
    return QueryResponse(
        answer=answer,
        citations=citations,
        confidence=confidence_label(pre_score),
        confidence_score=round(pre_score, 3),
        intent=intent,
        model_used=model_used,
        rewritten_query=rewritten_query,
    )

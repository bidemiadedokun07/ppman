"""
Request/response schemas for the /query endpoint. Kept intentionally small,
this is the contract the real web app will eventually call (see the
Infrastructure Requirements doc, "What to Request from the Web App
Developer" section, for the production version of this contract with auth).
"""
from pydantic import BaseModel, ConfigDict, Field


class ChatTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class QueryRequest(BaseModel):
    question: str
    conversation_history: list[ChatTurn] = Field(default_factory=list)
    # In production this comes from the validated session token, not the
    # request body. It is a plain field here only so the test frontend can
    # simulate different roles without a real auth system.
    user_role: str = "public"


class Citation(BaseModel):
    source_document: str
    hierarchy_path: str | None = None
    page_number: int | None = None


class QueryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # allow the model_used field name below

    answer: str
    citations: list[Citation]
    confidence: str  # "high" | "medium" | "low"
    confidence_score: float
    intent: str  # "simple" | "complex" | "analytics" | "reference"
    model_used: str
    rewritten_query: str

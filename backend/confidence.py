"""
Confidence scoring (see Design Document, Section 6): a rule-based score
computed from retrieval and grounding signals, not a learned model. This
is what gates whether an answer is shown directly, shown with a caveat,
or replaced with a "not found" response.
"""
from backend.retrieval import RetrievedChunk
from backend.config import config


def score_from_chunks(chunks: list[RetrievedChunk]) -> float:
    """
    Simple, inspectable scoring: the top similarity score dominates, with a
    small bonus if multiple chunks agree (several chunks above a reasonable
    similarity bar), and a penalty if nothing cleared a minimum bar at all.
    """
    if not chunks:
        return 0.0
    top = chunks[0].similarity
    supporting = sum(1 for c in chunks if c.similarity >= 0.55)
    agreement_bonus = min(0.1, 0.03 * max(0, supporting - 1))
    return min(1.0, max(0.0, top + agreement_bonus))


def score_from_reference_match(similarity: float, matched_by: str) -> float:
    if matched_by == "exact_key":
        return 0.97
    return max(0.0, min(1.0, similarity))


def score_from_structured_result(rows: list[dict]) -> float:
    """A successful, non-empty SQL result is high confidence by construction;
    the numbers came from the database, not a guess."""
    return 0.95 if rows else 0.2


def confidence_label(score: float) -> str:
    if score >= config.CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= config.CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"

"""
Combined query rewriting + intent classification.

Design rationale (see Design Document, Section 2 and Section 3): a
multi-turn chat needs conversation history condensed into a
self-contained query before retrieval, and every question needs an
intent label to route to the right model tier. Both are small, cheap
tasks, so they are combined into a single Gemini 2.5 Flash-Lite call
returning structured JSON, rather than two separate model round trips.
"""
import json
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

from backend.config import config
from backend.models import ChatTurn

vertexai.init(project=config.GCP_PROJECT_ID, location=config.GCP_REGION)
_classifier_model = GenerativeModel(config.MODEL_CLASSIFIER)

_SYSTEM_PROMPT = """You are a query preprocessing step for a compliance knowledge assistant.

Given recent conversation history and the user's latest message, do two things:
1. Rewrite the latest message into a single, self-contained question that
   does not depend on the prior turns to make sense. Resolve pronouns and
   references to earlier turns explicitly. If the latest message is already
   self-contained, return it unchanged.
2. Classify the rewritten question into exactly one of these intents:
   - "simple": a direct, single-fact lookup answerable from one policy passage
   - "complex": requires comparing or synthesizing multiple documents/sections
   - "analytics": requires computation or aggregation over structured data
   - "reference": asks to look up a specific record (e.g. a code, name, or
     mapping) rather than policy text

Respond ONLY with JSON in this exact shape, no other text:
{"rewritten_query": "...", "intent": "simple|complex|analytics|reference"}
"""


def rewrite_and_classify(latest_message: str, history: list[ChatTurn]) -> tuple[str, str]:
    history_text = "\n".join(f"{turn.role}: {turn.content}" for turn in history[-6:])
    prompt = (
        f"{_SYSTEM_PROMPT}\n\nConversation history:\n{history_text or '(none)'}"
        f"\n\nLatest message: {latest_message}"
    )

    response = _classifier_model.generate_content(
        prompt,
        generation_config=GenerationConfig(
            temperature=0.0,
            max_output_tokens=256,
            response_mime_type="application/json",
        ),
    )

    try:
        parsed = json.loads(response.text)
        rewritten = parsed["rewritten_query"].strip()
        intent = parsed["intent"].strip().lower()
        if intent not in {"simple", "complex", "analytics", "reference"}:
            intent = "simple"
        return rewritten, intent
    except (json.JSONDecodeError, KeyError, AttributeError):
        # Fail safe: if the classifier call itself misbehaves, fall back to
        # treating the raw message as self-contained and simple, rather than
        # blocking the request entirely.
        return latest_message, "simple"

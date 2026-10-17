"""
Step 2: Intent. Keyword rules first (fast, free, predictable).
Qwen3 is asked only when the rules find nothing or two intents tie.
Rules: rules.json -> intent
"""
from __future__ import annotations

from app.config import compile_patterns, rules
from app.core.models import Intent
from app.llm.client import LLMClient

_RULES = [(Intent(r["intent"]), compile_patterns(r["patterns"])) for r in rules["intent"]["rules"]]
_MARGIN = rules["intent"]["dominance_margin"]


def _keyword_intent(message: str) -> tuple[Intent | None, int]:
    """Return (intent or None, number of matching patterns).
    If several intents match, pick one only when it is clearly ahead."""
    hits: dict[Intent, int] = {}
    for intent, patterns in _RULES:
        count = sum(1 for p in patterns if p.search(message))
        if count:
            hits[intent] = count

    if not hits:
        return None, 0
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) == 1 or ranked[0][1] >= ranked[1][1] + _MARGIN:
        return ranked[0]
    return None, len(hits)


def resolve_intent(message: str, llm: LLMClient, trace) -> Intent:
    """Keywords first, then the LLM. Records in the trace which one decided."""
    intent, _ = _keyword_intent(message)
    if intent is not None:
        trace.intent_source = "keyword"
        trace.note(f"intent by keyword: {intent.value}")
        return intent

    trace.intent_source = "llm"
    intent = llm.classify_intent(message)
    trace.note(f"intent by llm: {intent.value}")
    return intent
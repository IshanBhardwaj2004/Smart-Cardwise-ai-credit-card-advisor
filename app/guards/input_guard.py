"""
Step 1: Input guard. Checks the message first: approval promises, tax advice,
non-card topics, prompt injection and sensitive data are refused here.
No LLM, no server call. Rules: rules.json -> guards.input_block
"""
from __future__ import annotations

from app.config import compile_patterns, rules
from app.core.models import GuardResult

_RULES = [
    (r["name"], compile_patterns(r["patterns"]), r["message"])
    for r in rules["guards"]["input_block"]
]


def check_input(message: str) -> GuardResult:
    text = message or ""
    for name, patterns, user_message in _RULES:
        if any(p.search(text) for p in patterns):
            return GuardResult(blocked=True, reason=f"input_block:{name}", user_message=user_message)
    return GuardResult(blocked=False)
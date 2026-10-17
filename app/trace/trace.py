"""
Trace object. Every request gets one trace, and every pipeline step writes its
work here. This is the evidence when something fails:
"what the server sent" vs "what the bot said".
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from app.config import compile_patterns, rules
from app.core.models import (
    Intent,
    Slots,
    ToolCallRecord,
    ValidationFlag,
)


# card numbers, Aadhaar, PAN, OTP and similar data are never written to trace files
_REDACT = compile_patterns(rules["guards"]["redact_patterns"])


def redact(text: str) -> str:
    for pattern in _REDACT:
        text = pattern.sub("[redacted]", text)
    return text


class Trace:
    def __init__(self, user_message: str, session_id: str | None = None):
        self.request_id: str = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.ts: float = time.time()
        self.user_message = redact(user_message or "")

        # output of every stage is collected here
        self.input_guard: dict[str, Any] = {}
        self.intent: Intent | None = None
        self.intent_source: str | None = None       # "keyword", "llm", "session", "spending" or "card_name"
        self.slots: Slots | None = None
        self.clarify_question: str | None = None
        self.workflow: str | None = None
        self.tool_calls: list[ToolCallRecord] = []   # raw server responses = evidence
        self.validation_flags: list[ValidationFlag] = []
        self.validated_data: Any = None              # what the LLM received
        self.llm_raw_reply: str | None = None
        self.output_guard: dict[str, Any] = {}
        self.final_reply: str | None = None
        self.notes: list[str] = []                   # English debug notes

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def add_tool_call(self, rec: ToolCallRecord) -> None:
        self.tool_calls.append(rec)

    def to_dict(self) -> dict[str, Any]:
        """The whole trace in JSON-serializable form (for failures.md / debugging)."""
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "ts": self.ts,
            "user_message": self.user_message,
            "input_guard": self.input_guard,
            "intent": self.intent.value if self.intent else None,
            "intent_source": self.intent_source,
            "slots": self.slots.model_dump() if self.slots else None,
            "clarify_question": self.clarify_question,
            "workflow": self.workflow,
            "tool_calls": [t.model_dump() for t in self.tool_calls],
            "validation_flags": [f.model_dump() for f in self.validation_flags],
            "validated_data": self.validated_data,
            "llm_raw_reply": self.llm_raw_reply,
            "output_guard": self.output_guard,
            "final_reply": self.final_reply,
            "notes": self.notes,
        }
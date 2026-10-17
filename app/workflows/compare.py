"""
compare_cards workflow: 2-3 matched cards side by side (the server takes at most 3).
"""
from __future__ import annotations

from app.core.models import ToolCallRecord
from app.mcp import schema
from app.mcp.client import MCPClient


def run(slots, mcp: MCPClient, trace):
    trace.workflow = "compare"
    if len(slots.card_ids) < 2:
        return {"_need": "two_cards"}

    args = {schema.ARGS["card_aliases"]: slots.card_ids[:schema.OPTIONS["max_compare"]]}
    raw = mcp.call(schema.TOOL_COMPARE, args)
    trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_COMPARE, arguments=args, raw_response=raw, ok=True))
    return raw
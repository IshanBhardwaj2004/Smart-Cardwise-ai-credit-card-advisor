"""
recommend_cards workflow: each spend goes in the server's own key, in that key's unit
(e.g. {"amazon_spends": 15000, "flights_annual": 150000}).
"""
from __future__ import annotations

from app.core.models import ToolCallRecord
from app.mcp import schema
from app.mcp.client import MCPClient


def run(slots, mcp: MCPClient, trace):
    trace.workflow = "recommend"
    args = {s.key: s.amount for s in slots.spends}
    args[schema.ARGS["top_n"]] = schema.OPTIONS["recommend_top_n"]
    args[schema.ARGS["response_format"]] = schema.OPTIONS["recommend_format"]

    raw = mcp.call(schema.TOOL_RECOMMEND, args)
    trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_RECOMMEND, arguments=args, raw_response=raw, ok=True))
    return raw
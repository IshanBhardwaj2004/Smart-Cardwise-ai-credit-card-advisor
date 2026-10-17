"""
get_card_details workflow: full details of the matched card.
"""
from __future__ import annotations

from app.core.models import ToolCallRecord
from app.mcp import schema
from app.mcp.client import MCPClient


def fetch(alias: str, mcp: MCPClient, trace):
    args = {schema.ARGS["card_alias"]: alias}
    raw = mcp.call(schema.TOOL_CARD_DETAILS, args)
    trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_CARD_DETAILS, arguments=args, raw_response=raw, ok=True))
    return raw


def run(slots, mcp: MCPClient, trace):
    trace.workflow = "card_details"
    if not slots.card_ids:
        return {"_need": "card"}
    return fetch(slots.card_ids[0], mcp, trace)
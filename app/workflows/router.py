"""
Step 6a: Capability router. Looks at intent + slots and decides which workflow runs.
Today it is mostly 1:1, but this is where an intent can get several workflows.
"""
from __future__ import annotations

from app.core.models import Intent
from app.workflows import card_details, compare, eligibility, recommend


def route(intent: Intent, slots, mcp, trace):
    """
    Send the intent to the right workflow and return its raw result.
    Future: pick between several workflows for one intent based on slots.
    """
    if intent == Intent.RECOMMEND:
        return recommend.run(slots, mcp, trace)
    if intent == Intent.CARD_DETAILS:
        return card_details.run(slots, mcp, trace)
    if intent == Intent.COMPARE:
        return compare.run(slots, mcp, trace)
    if intent == Intent.ELIGIBILITY:
        return eligibility.run(slots, mcp, trace)
    # no workflow beyond recommend / details / compare / eligibility
    return {"_unsupported": intent.value}
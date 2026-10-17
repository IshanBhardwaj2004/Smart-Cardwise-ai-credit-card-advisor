"""
MCP server format: tool names, argument names, response fields.
All from the "mcp" section of rules.json. If the server format changes, edit only rules.json.

The server sends the same thing under different names in different tools
(e.g. joining fee: "joining_fee" or "fees.joining"), so each field has several
candidate paths; the first one found wins.
Money comes as text ("₹1,180 (incl. GST)", "Free"); money() turns it into a number.
"""
from __future__ import annotations

import re
from typing import Any

from app.config import rules

_MCP = rules["mcp"]
TOOLS: dict[str, str] = _MCP["tools"]
ARGS: dict[str, str] = _MCP["args"]
OPTIONS: dict[str, Any] = _MCP["options"]
_RESP = _MCP["response"]
_FIELDS: dict[str, list[str]] = _RESP["fields"]
_ZERO_WORDS = [w.lower() for w in _RESP["zero_words"]]
LPA_UNIT: int = _RESP["lpa_unit"]
_UNITS = _MCP["spend_key_units"]

TOOL_RECOMMEND = TOOLS["recommend"]
TOOL_CARD_DETAILS = TOOLS["card_details"]
TOOL_LIST_CARDS = TOOLS["list_cards"]
TOOL_COMPARE = TOOLS["compare"]
TOOL_CHECK_ELIGIBILITY = TOOLS["check_eligibility"]
TOOL_RESOLVE = TOOLS["resolve"]

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _path(obj: Any, path: str):
    """Read a dotted path like 'fees.joining'."""
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def field(card: Any, key: str, default=None):
    """Field by its rules.json name: the first candidate path found."""
    for path in _FIELDS.get(key, [key]):
        value = _path(card, path)
        if value is not None:
            return value
    return default


def money(value) -> float | None:
    """Server money as a number: 9000 -> 9000, "₹9,000" -> 9000,
    "Free" / "Free (waived...)" -> 0, "₹1,179 (₹999 + GST)" -> 1179 (first number)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if any(text.startswith(w) for w in _ZERO_WORDS):
        return 0.0
    m = _NUMBER_RE.search(text)
    return float(m.group().replace(",", "")) if m else None


def format_inr(value) -> str:
    """Indian commas: 180000 -> 1,80,000"""
    n = int(round(value))
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def number(card: Any, key: str) -> int | None:
    """Field as whole rupees (parsed if it is text)."""
    value = money(field(card, key))
    return None if value is None else int(round(value))


def text(card: Any, key: str) -> str | None:
    """Field as the server sent it, as text (shown as is in the UI)."""
    value = field(card, key)
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value).strip()


def card_label(card: Any) -> str:
    name = field(card, "card_name") or field(card, "card_id") or "Card"
    return str(name).strip()


def card_id(card: Any):
    return field(card, "card_id")


def benefit_titles(card: Any, limit: int) -> list[str]:
    items = field(card, "benefits") or []
    titles = []
    for b in items:
        title = field(b, "benefit_title") if isinstance(b, dict) else b
        if title:
            titles.append(str(title).strip())
    return titles[:limit]


def cards_in(data: Any) -> list[dict]:
    """Card list from a response: the first list key found, else the response itself is one card."""
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if not isinstance(data, dict):
        return []
    for key in _RESP["card_lists"]:
        if isinstance(data.get(key), list):
            return [c for c in data[key] if isinstance(c, dict)]
    if any(k in data for k in _RESP["single_card_marker"]):
        return [data]
    return []


def error_of(data: Any):
    return field(data, "error") if isinstance(data, dict) else None


def key_unit(spend_key: str) -> str:
    """Unit of a spending key from its name: *_annual = year, *_quarterly = quarter, others month.
    Keys that break the naming rule (life_insurance is annual) are listed in overrides."""
    if spend_key in _UNITS.get("overrides", {}):
        return _UNITS["overrides"][spend_key]
    for suffix, unit in _UNITS["suffixes"].items():
        if spend_key.endswith(suffix):
            return unit
    return _UNITS["default"]
"""
Finds card names in the message by matching against the server's list_cards list (no LLM guessing).
  - the list is fetched once and cached (rules.json -> mcp.options)
  - matching uses the words of the card name; if two cards match almost equally, both are returned (alternatives)
  - common words (credit, card) are worked out from the data, not hardcoded
  - fuzzy matching for typos ("regaliaa" -> "regalia"); the server's resolver does not handle typos
Limits: rules.json -> matching
"""
from __future__ import annotations

import re
import time

from app.config import rules
from app.core.models import ToolCallRecord
from app.mcp import schema
from app.mcp.client import MCPClient

try:
    from rapidfuzz import fuzz

    def _similarity(a: str, b: str) -> float:
        return fuzz.ratio(a, b)
except ImportError:
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100

_CFG = rules["matching"]
_WORD_RE = re.compile(r"[a-z0-9]+")
_cache: dict = {"at": 0.0, "cards": []}


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(str(text).lower()) if len(w) >= _CFG["min_word_len"]]


def _tokens(text: str) -> list[tuple[str, int]]:
    """Message words with their position (word number).
    Short forms are expanded at the same position (amex -> american, express)."""
    out = []
    for i, w in enumerate(_words(text)):
        out.append((w, i))
        out.extend((x, i) for x in _words(_CFG["short_forms"].get(w, "")))
    return out


def _word_matches(card_word: str, msg_word: str) -> bool:
    if card_word == msg_word:
        return True
    if min(len(card_word), len(msg_word)) < _CFG["min_fuzzy_len"]:
        return False
    return _similarity(card_word, msg_word) >= _CFG["word_match"]


def card_list(mcp: MCPClient, trace) -> list[dict]:
    """The server's full card list (from cache; refetched when stale)."""
    max_age = schema.OPTIONS["card_list_cache_seconds"]
    if _cache["cards"] and time.time() - _cache["at"] < max_age:
        trace.note(f"card list from cache ({len(_cache['cards'])} cards)")
        return _cache["cards"]

    args = {schema.ARGS["limit"]: schema.OPTIONS["list_limit"],
            schema.ARGS["response_format"]: schema.OPTIONS["list_format"]}
    raw = mcp.call(schema.TOOL_LIST_CARDS, args)
    cards = schema.cards_in(raw)
    # the full list is too big for every trace, so only the count
    trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_LIST_CARDS, arguments=args,
                                       raw_response={"cards_returned": len(cards)}, ok=bool(cards)))
    if cards:
        _cache.update(at=time.time(), cards=cards)
    return cards


def card_index(mcp: MCPClient, trace) -> dict[str, str]:
    """alias -> name in the list (for the name mismatch check and clean display names)."""
    return {schema.card_id(c): schema.card_label(c) for c in card_list(mcp, trace) if schema.card_id(c)}


def _common_words(card_words: list[set[str]]) -> set[str]:
    counts: dict[str, int] = {}
    for ws in card_words:
        for w in ws:
            counts[w] = counts.get(w, 0) + 1
    limit = max(1, len(card_words) * _CFG["common_share"])
    return {w for w, n in counts.items() if n > limit}


def find_cards_in_text(text: str, mcp: MCPClient, trace) -> list[dict]:
    """All card names in the message, in text order: [{card_id, card_name, alternatives}]."""
    cards = card_list(mcp, trace)
    if not cards:
        return []

    card_words = [set(_words(schema.card_label(c))) for c in cards]
    common = _common_words(card_words)
    tokens = _tokens(text)

    scored = []
    for card, ws in zip(cards, card_words):
        key_words = (ws - common) or ws
        if not key_words:
            continue
        # where each card word appears in the message
        positions = [[pos for w, pos in tokens if _word_matches(kw, w)] for kw in key_words]
        hit_lists = [p for p in positions if p]
        if len(hit_lists) / len(key_words) < _CFG["card_match"]:
            continue
        used = _closest_group(hit_lists)
        # the card's words must be close together in the message, not scattered
        if (max(used) - min(used) + 1) - len(used) > _CFG["max_word_gap"]:
            continue
        scored.append((len(hit_lists) / len(key_words), len(used), min(used), frozenset(used), card))

    # best match first; drop a card whose words were all taken by an earlier card.
    # nearly equal score on the same words = the user's meaning is unclear (alternatives)
    scored.sort(key=lambda s: (-s[0], -s[1]))
    picked, covered = [], set()
    for item in scored:
        if item[3] <= covered:
            twin = next((p for p in picked if p[3] == item[3] and p[0] - item[0] <= _CFG["tie_margin"]), None)
            if twin:
                twin[5].append(schema.card_label(item[4]))
            continue
        picked.append((*item, []))
        covered |= item[3]
    picked.sort(key=lambda p: p[2])

    found = [{"card_id": schema.card_id(p[4]), "card_name": schema.card_label(p[4]), "alternatives": p[5]}
             for p in picked]
    trace.note(f"cards found in message: {[f['card_name'] for f in found]}")
    return found


def _closest_group(hit_lists: list[list[int]]) -> set[int]:
    """Pick one position per word so they are as close together as possible."""
    best = None
    for anchor in {p for hits in hit_lists for p in hits}:
        group = {min(hits, key=lambda p: abs(p - anchor)) for hits in hit_lists}
        span = max(group) - min(group)
        if best is None or span < best[0]:
            best = (span, group)
    return best[1]
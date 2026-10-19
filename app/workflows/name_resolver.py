"""
Finds card names in the message by matching against the server's list_cards list (no LLM guessing).
  - the list is fetched once and cached (rules.json -> mcp.options)
  - matching uses the words of the card name; if two cards match almost equally, both are returned (alternatives)
  - common words (credit, card) are worked out from the data, not hardcoded
  - fuzzy matching for typos ("regaliaa" -> "regalia"); the server's resolver does not handle typos
  - accents ignored ("MARQUÉE" = "marquee"); joined words matched ("simplyclick" = "simply click")
  - a partial name that fits several cards ("tata neu", "swiggy hdfc") is returned with alternatives,
    so the bot asks which one instead of silently picking one
Limits: rules.json -> matching
"""
from __future__ import annotations

import re
import time
import unicodedata

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


def _plain(text: str) -> str:
    """Lower case without accents: "MARQUÉE" -> "marquee"."""
    decomposed = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(_plain(text)) if len(w) >= _CFG["min_word_len"]]


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


def _positions(word: str, seq: list[str], tokens: list[tuple[str, int]]) -> list[int]:
    """Where a card word appears in the message, also inside a joined word ("simplyclick")."""
    hits = [pos for w, pos in tokens if _word_matches(word, w)]
    i = seq.index(word)
    joined = []
    if i + 1 < len(seq):
        joined.append(word + seq[i + 1])
    if i:
        joined.append(seq[i - 1] + word)
    hits += [pos for w, pos in tokens for j in joined if _word_matches(j, w)]
    return sorted(set(hits))


def find_cards_in_text(text: str, mcp: MCPClient, trace) -> list[dict]:
    """All card names in the message, in text order: [{card_id, card_name, alternatives}]."""
    cards = card_list(mcp, trace)
    if not cards:
        return []

    seqs = [_words(schema.card_label(c)) for c in cards]
    card_words = [set(s) for s in seqs]
    common = _common_words(card_words)
    tokens = _tokens(text)
    # how many cards each word appears in (rare words like "neu" identify a family of cards)
    spread: dict[str, int] = {}
    for ws in card_words:
        for w in ws:
            spread[w] = spread.get(w, 0) + 1

    scored, partial = [], []
    for card, seq, ws in zip(cards, seqs, card_words):
        key_words = (ws - common) or ws
        if not key_words:
            continue
        hits = {kw: _positions(kw, seq, tokens) for kw in key_words}
        hit_lists = [p for p in hits.values() if p]
        if not hit_lists:
            continue
        used = _closest_group(hit_lists)
        # the card's words must be close together in the message, not scattered
        if (max(used) - min(used) + 1) - len(used) > _CFG["max_word_gap"]:
            continue
        matched = frozenset(kw for kw, p in hits.items() if p)
        entry = (len(hit_lists) / len(key_words), len(used), min(used), frozenset(used), card, matched)
        if entry[0] >= _CFG["card_match"]:
            scored.append(entry)
        elif (len(matched) >= _CFG["fallback_min_words"]
              and all(spread[w] <= _CFG["distinct_word_max_cards"] for w in matched)):
            partial.append(entry)   # e.g. "tata neu": too short for one card, but clearly a card family

    if not scored and partial:
        # no full match: the cards sharing the most distinctive words are the candidates
        best = max(len(p[5]) for p in partial)
        scored = [p for p in partial if len(p[5]) == best]

    # best match first; drop a card whose words were all taken by an earlier card.
    # nearly equal score on the same words = the user's meaning is unclear (alternatives)
    scored.sort(key=lambda s: (-s[0], -s[1]))
    picked, covered = [], set()
    for item in scored:
        if item[3] <= covered:
            twin = next((p for p in picked if p[3] == item[3] and p[0] - item[0] <= _CFG["tie_margin"]), None)
            if twin and len(twin[6]) < _CFG["max_alternatives"]:
                twin[6].append(schema.card_label(item[4]))
            continue
        picked.append((*item, []))
        covered |= item[3]

    # a partial name ("swiggy hdfc") that also fits other cards is unclear: list them too
    by_name = {schema.card_label(c): ws for c, ws in zip(cards, card_words)}
    for p in picked:
        if p[0] >= 1:
            continue
        name = schema.card_label(p[4])
        for other, ws in by_name.items():
            if (len(p[6]) < _CFG["max_alternatives"] and other != name and other not in p[6]
                    and all(any(_word_matches(m, w) for w in ws) for m in p[5])
                    and not any(other == schema.card_label(q[4]) for q in picked)):
                p[6].append(other)
    picked.sort(key=lambda p: p[2])

    found = [{"card_id": schema.card_id(p[4]), "card_name": schema.card_label(p[4]), "alternatives": p[6]}
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

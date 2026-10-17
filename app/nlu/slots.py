"""
Step 3: Slot extractor. Reads from the message:
  - spending: each amount + its category (server spending key) + period
  - income, job type (salaried / self-employed), pincode
Rules (words, units, category patterns): rules.json -> slots.

Period: what the user said ("a month", "yearly"); if not said, the key's own unit
(server convention: *_annual is yearly, the rest monthly).
"4 times a year, 15k each trip" -> 60k yearly.
Amounts with no category found here go to loose_amounts; the pipeline asks the
server's resolver about them (brands: Myntra, DMart...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import compile_patterns, rules, words_pattern
from app.core.models import LooseAmount, Slots, Spend
from app.mcp import schema

_CFG = rules["slots"]
_KEYS = {key: compile_patterns(pats) for key, pats in _CFG["spend_keys"].items()}
_UNITS = {k.lower(): v for k, v in _CFG["units"].items()}
_UNIT_PERIODS = {k.lower(): v for k, v in _CFG["unit_periods"].items()}
_MONTHLY = words_pattern(_CFG["monthly_words"])
_YEARLY = words_pattern(_CFG["yearly_words"])
_INCOME = words_pattern(_CFG["income_words"])
_PINCODE_WORDS = words_pattern(_CFG["pincode_words"])
_EMPLOYMENT = {value: words_pattern(words) for value, words in _CFG["employment"].items()}
# 6 digits, but not part of "1,50,000" or "1500000" (blocked only when a digit follows a comma/point)
_PINCODE_RE = re.compile(r"(?<!\d)(?<!\d[,.])[1-9]\d{5}(?!\d)(?![,.]\d)")


def _alternation(items) -> str:
    return "|".join(sorted((re.escape(i) for i in items), key=len, reverse=True))


_AMOUNT_RE = re.compile(
    rf"(?<!\w)(?:{_alternation(_CFG['currency_prefixes'])})?\s?"
    rf"(\d[\d,]*(?:\.\d+)?)\s?({_alternation(_UNITS)})?\b",
    re.IGNORECASE,
)
_CURRENCY_BEFORE = re.compile(rf"(?:{_alternation(_CFG['currency_prefixes'])})\s?$", re.IGNORECASE)

# "4 times a year" / "6 trips per year" / "2 baar mahine"
_FREQ = _CFG["frequency"]
_FREQ_PERIOD_WORDS = {w: p for p, words in _FREQ["periods"].items() for w in words}
_FREQ_RE = re.compile(
    rf"(\d+)\s*(?:{_alternation(_FREQ['pattern_words']['times'])})\s*(?:{_alternation(_FREQ['pattern_words']['per'])})?\s*"
    rf"({_alternation(_FREQ_PERIOD_WORDS)})\b",
    re.IGNORECASE,
)
_EACH = words_pattern(_FREQ["each_words"])


@dataclass
class _Amount:
    value: int
    start: int
    end: int
    unit_period: str | None   # units like "lpa" carry their own period


# ---------- helpers ----------

def _pincode(text: str, expecting: str | None, bare_ok: bool) -> tuple[str | None, tuple[int, int] | None]:
    """6 digits after a pincode word. If the bot asked for the pincode, or this is an eligibility
    question, also without the word, as long as it doesn't look like money (no ₹ before, no lakh/month/salary after)."""
    word = _PINCODE_WORDS.search(text)
    if word:
        m = _PINCODE_RE.search(text, word.end())
        if m:
            return m.group(), m.span()
    if expecting == "pincode" or bare_ok:
        blockers = _CFG["pincode_blockers"]
        for m in _PINCODE_RE.finditer(text):
            before = text[max(0, m.start() - blockers["before"]):m.start()]
            after = text[m.end():m.end() + blockers["after"]]
            looks_like_money = (_CURRENCY_BEFORE.search(before) or _INCOME.search(before) or _INCOME.search(after)
                                or _MONTHLY.search(after) or _YEARLY.search(after)
                                or re.match(rf"\s?({_alternation(_UNITS)})\b", after, re.IGNORECASE))
            if not looks_like_money:
                return m.group(), m.span()
    return None, None


def _employment(text: str) -> str | None:
    for value, pattern in _EMPLOYMENT.items():
        if pattern.search(text):
            return value
    return None


def _parse_amounts(text: str, skip: tuple[int, int] | None) -> list[_Amount]:
    found = []
    for m in _AMOUNT_RE.finditer(text):
        if skip and m.start(1) < skip[1] and m.end(1) > skip[0]:
            continue  # this is the pincode, not an amount
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        value = int(round(value * _UNITS.get(unit, 1)))
        if value >= _CFG["min_spend"]:
            found.append(_Amount(value, m.start(1), m.end(), _UNIT_PERIODS.get(unit)))
    return found


def _first_period(window: str) -> str | None:
    month, year = _MONTHLY.search(window), _YEARLY.search(window)
    if month and (not year or month.start() < year.start()):
        return "month"
    return "year" if year else None


def _window_after(text: str, amounts: list[_Amount], i: int) -> str:
    next_start = amounts[i + 1].start if i + 1 < len(amounts) else len(text)
    return text[amounts[i].end:min(next_start, amounts[i].end + _CFG["after_window"])]


def _stated_periods(text: str, amounts: list[_Amount]) -> list[str | None]:
    """Period the user stated for each amount (look after it, then before). None if not stated."""
    periods = []
    for i, a in enumerate(amounts):
        if a.unit_period:
            periods.append(a.unit_period)
            continue
        prev_end = amounts[i - 1].end if i else 0
        before = text[max(prev_end, a.start - _CFG["before_window"]):a.start]
        periods.append(_first_period(_window_after(text, amounts, i)) or _first_period(before))
    return periods


def _apply_frequency(text: str, amounts: list[_Amount], periods: list[str | None]) -> None:
    """'4 times a year, 15k each trip' -> 60k yearly (when 'each' follows the amount)."""
    freq = _FREQ_RE.search(text)
    if not freq:
        return
    count, period = int(freq.group(1)), _FREQ_PERIOD_WORDS[freq.group(2).lower()]
    for i, a in enumerate(amounts):
        if a.start <= freq.start() < a.end:
            continue
        if _EACH.search(_window_after(text, amounts, i)):
            a.value *= count
            periods[i] = period


def _keys_in_text(text: str) -> list[tuple[str, int]]:
    """Every spending key found: (key, first position in text), after conflict rules."""
    found = {}
    for key, patterns in _KEYS.items():
        starts = [m.start() for p in patterns if (m := p.search(text))]
        if starts:
            found[key] = min(starts)
    # "groceries from blinkit": drop the generic (offline) key when a specific (online) one is close
    for rule in _CFG["key_conflicts"]:
        keep, drop = found.get(rule["keep"]), found.get(rule["drop"])
        if keep is not None and drop is not None and abs(keep - drop) <= rule["within"]:
            del found[rule["drop"]]
    return list(found.items())


def _distance(a: _Amount, pos: int, key_first: bool) -> int:
    # the side matching the user's writing style is cheap, the other side costs more
    penalty = _CFG["wrong_side_penalty"]
    if pos >= a.end:
        gap = pos - a.end
        return gap * penalty if key_first else gap
    gap = a.start - pos
    return gap if key_first else gap * penalty


def _pair(amounts: list[_Amount], keys: list[tuple[str, int]]) -> dict[int, str]:
    """Amount -> nearest key (each used once). Return {amount index: key}."""
    if not amounts or not keys:
        return {}
    key_first = min(pos for _, pos in keys) < amounts[0].start
    candidates = sorted(
        (_distance(a, pos, key_first), ai, ki)
        for ai, a in enumerate(amounts)
        for ki, (_, pos) in enumerate(keys)
    )
    used_k, pairs = set(), {}
    for _, ai, ki in candidates:
        if ai not in pairs and ki not in used_k:
            pairs[ai] = keys[ki][0]
            used_k.add(ki)
    return pairs


def _income_index(text: str, amounts: list[_Amount], expecting: str | None) -> int | None:
    """The amount nearest the income word (after or before: 'salary 60k', '2 lakh salary')."""
    word = _INCOME.search(text)
    if not word:
        return 0 if expecting == "income" and amounts else None
    window = _CFG["income_window"]
    best = None
    for i, a in enumerate(amounts):
        gap = a.start - word.end() if a.start >= word.start() else word.start() - a.end
        if gap <= window and (best is None or gap < best[0]):
            best = (gap, i)
    return best[1] if best else None


def to_spend(key: str, amount: int, period: str | None) -> Spend:
    """User's amount -> the server key's unit. If no period was stated, use the key's own unit."""
    unit = schema.key_unit(key)
    period = period or unit
    if period == unit:
        value = amount
    elif period == "month" and unit == "year":
        value = amount * 12
    elif period == "year" and unit == "month":
        value = round(amount / 12)
    else:
        value = amount
    annual = value * 12 if unit == "month" else value
    return Spend(key=key, amount=value, unit=unit, annual_amount=annual)


# ---------- main ----------

def extract_slots(message: str, expecting: str | None = None, bare_pincode_ok: bool = False) -> Slots:
    """expecting: the question asked last time ("income", "pincode"...), so a short reply
    ("50k", "110001") lands in the right place. bare_pincode_ok: this is an eligibility question."""
    text = message or ""
    pincode, pin_span = _pincode(text, expecting, bare_pincode_ok)
    amounts = _parse_amounts(text, pin_span)
    periods = _stated_periods(text, amounts)
    _apply_frequency(text, amounts, periods)

    income_idx = _income_index(text, amounts, expecting)
    monthly_income = None
    if income_idx is not None:
        a = amounts[income_idx]
        monthly_income = a.value // 12 if periods[income_idx] == "year" else a.value

    keys = _keys_in_text(text)
    spend_idx = [i for i in range(len(amounts)) if i != income_idx]
    pairs = _pair([amounts[i] for i in spend_idx], keys)

    spends, loose = [], []
    for j, i in enumerate(spend_idx):
        a, period = amounts[i], periods[i]
        if j in pairs:
            spends.append(to_spend(pairs[j], a.value, period))
        else:
            prev_end = amounts[i - 1].end if i else 0
            next_start = amounts[i + 1].start if i + 1 < len(amounts) else len(text)
            snippet = text[prev_end:next_start].strip(" ,.;")
            loose.append(LooseAmount(amount=a.value, period=period, snippet=snippet))

    return Slots(
        spends=spends,
        loose_amounts=loose,
        mentioned_keys=[k for k, _ in keys if k not in {s.key for s in spends}],
        monthly_income=monthly_income,
        employment=_employment(text),
        pincode=pincode,
    )
"""
Step 12: Output guard. Before the LLM reply reaches the user:
  1. Every money figure in the reply must exist in the data:
     "₹8,500", "8,500 rupees", "₹1.8 lakh" and large numbers without ₹.
     A rounded figure ("about ₹37k", "₹8.4k") passes only if a data figure rounds to it.
     Amounts in the data are read with their units too ("₹4 lakh" = 4,00,000).
  2. No banned phrase (approval promise, tax advice, asking for an OTP...).
Rules: rules.json -> guards.banned_output, slots.units
"""
from __future__ import annotations

import re

from app.config import rules

_BANNED = [(b["name"], re.compile(b["pattern"], re.IGNORECASE)) for b in rules["guards"]["banned_output"]]
_MIN_CHECKED = rules["guards"]["min_checked_amount"]
_ROUND_TOL = rules["guards"]["rounded_tolerance"]
_SPACES_RE = re.compile(r"\s+")
_UNITS = {k.lower(): v for k, v in rules["slots"]["units"].items()}

_UNIT = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_NUM = r"(-?\d[\d,]*(?:\.\d+)?)"
# amounts with ₹, or with "rupees" / "/-" (units included)
_MONEY_RE = re.compile(
    rf"(?:₹|\brs\.?|\binr)\s?{_NUM}\s?({_UNIT})?\b|{_NUM}\s?({_UNIT})?\s?(?:rupees?\b|/-)",
    re.IGNORECASE,
)
# large numbers (100+) without ₹, but not percentages
_BARE_RE = re.compile(r"(?<![\w.,₹-])(\d{1,3}(?:,\d{2,3})+|\d{3,})(?![\d,]*\s?%)")
_DIGITS_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _to_int(num: str, unit: str | None) -> int | None:
    try:
        value = float(num.replace(",", ""))
    except ValueError:
        return None
    return int(round(value * _UNITS.get((unit or "").lower(), 1)))


def _numbers_in_reply(text: str) -> set[int]:
    # LLMs often write "₹1\u202f lakh" (narrow space + space); one space keeps the unit attached
    text = _SPACES_RE.sub(" ", text)
    found: set[int] = set()
    covered: list[tuple[int, int]] = []
    for m in _MONEY_RE.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        value = _to_int(num, unit)
        if value is not None:
            found.add(abs(value))
            covered.append(m.span())
    for m in _BARE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in covered):
            continue
        value = _to_int(m.group(1), None)
        if value is not None:
            found.add(value)
    return found


def _numbers_in_data(data) -> set[int]:
    """Every number inside the data (including inside strings) is allowed."""
    allowed: set[int] = set()

    def walk(obj):
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            allowed.add(abs(int(round(obj))))
        elif isinstance(obj, str):
            for m in _DIGITS_RE.finditer(obj):
                value = _to_int(m.group(), None)
                if value is not None:
                    allowed.add(value)
            # amounts written with a unit in the data itself ("waived if you spend ₹4 lakh")
            allowed.update(_numbers_in_reply(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(data)
    return allowed


def _rounded_from(n: int, allowed: set[int]) -> bool:
    """A rounded figure ("about ₹37k", "₹8.4k") is fine if a real data figure rounds to it (₹37,231, ₹8,421)."""
    if n < 1000 or n % 100:
        return False
    return any(a and abs(a - n) / a <= _ROUND_TOL for a in allowed)


def check_output(reply: str, data) -> dict:
    """Return: {"ok": bool, "problems": [...], "unverified_numbers": [...]}"""
    text = reply or ""
    problems = [f"banned_phrase:{name}" for name, pat in _BANNED if pat.search(text)]

    allowed = _numbers_in_data(data)
    unverified = sorted(n for n in _numbers_in_reply(text)
                        if n >= _MIN_CHECKED and n not in allowed and not _rounded_from(n, allowed))
    if unverified:
        problems.append(f"unverified_numbers:{unverified}")

    return {"ok": not problems, "problems": problems, "unverified_numbers": unverified}

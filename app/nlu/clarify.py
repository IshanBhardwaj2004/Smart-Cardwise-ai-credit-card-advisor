"""
Step 5: Clarify gate. If required info is missing, ask one direct question
instead of guessing.
Which question and in what order: rules.json -> clarify (per mode).
Mode = intent, with two eligibility modes: eligibility_card / eligibility_list.
"""
from __future__ import annotations

from app.config import rules
from app.core.models import Slots

# "missing" name -> check (True = this info is missing)
_CHECKS = {
    "spend_where": lambda s: not s.spends and bool(s.loose_amounts),   # amount given, but not where it goes
    "spend": lambda s: not s.spends,
    "card": lambda s: not s.card_ids,
    "two_cards": lambda s: len(s.card_ids) < 2,
    "income": lambda s: s.monthly_income is None,
    "employment": lambda s: s.employment is None,
    "pincode": lambda s: s.pincode is None,
}


def missing_info(mode: str, slots: Slots) -> tuple[str, str] | None:
    """First missing piece of info: (name, question), else None."""
    for item in rules["clarify"].get(mode, []):
        if _CHECKS[item["missing"]](slots):
            return item["missing"], item["question"]
    return None


def question_for(missing: str) -> str:
    """The question for this missing info (used by workflows)."""
    for items in rules["clarify"].values():
        for item in items:
            if item["missing"] == missing:
                return item["question"]
    return rules["messages"]["need_more"]
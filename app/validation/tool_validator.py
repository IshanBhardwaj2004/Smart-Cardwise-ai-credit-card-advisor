"""
Step 10: Tool output validator. Checks server data BEFORE the LLM sees it.
Each problem gets a flag: whose fault it looks like (mcp_tool / data), and whether
to warn the user or keep it as evidence (trace) only.
All checks and formulas: rules.json -> validation. No card lists.

Checks:
  - fees negative or unrealistically high               -> data
  - formula checks (net savings math)                   -> mcp_tool
  - every card ₹0 but still ranked                      -> mcp_tool
  - breakdown labelled "annual" but x12 = annual        -> mcp_tool
  - LPA and monthly minimum income disagree             -> data
  - "monthly" minimum that is really a yearly amount    -> data
  - card name differs from the card list (same alias)   -> data
  - most of the value is a milestone benefit            -> mcp_tool (evidence only)
"""
from __future__ import annotations

import re
from typing import Any

from app.config import rules
from app.core.models import ValidationFlag
from app.mcp import schema

_CFG = rules["validation"]
_WORD_RE = re.compile(r"[a-z0-9]+")


def _flag(where: str, cfg: dict, problem: str | None = None) -> ValidationFlag:
    return ValidationFlag(field=where, problem=problem or cfg["problem"],
                          suspected_fault=cfg["fault"], warn_user=cfg["warn_user"])


def _fee_flags(card: dict, name: str) -> list[ValidationFlag]:
    flags = []
    for key in ("joining_fee", "annual_fee"):
        fee = schema.number(card, key)
        if fee is None:
            continue
        if fee < 0:
            flags.append(ValidationFlag(field=f"{name}.{key}", problem=f"{key} is negative ({fee})",
                                        suspected_fault="data"))
        elif fee > _CFG["max_fee"]:
            flags.append(ValidationFlag(field=f"{name}.{key}", problem=f"{key} is unrealistically high ({fee})",
                                        suspected_fault="data"))
    return flags


def _formula_flags(card: dict, name: str) -> list[ValidationFlag]:
    flags = []
    tol = _CFG["rounding_tolerance"]
    for check in _CFG["formula_checks"]:
        result = schema.number(card, check["result"])
        parts = {k: schema.number(card, k) for k in check["plus"] + check["minus"]}
        if result is None or None in parts.values():
            continue
        if check.get("only_if_nonzero") and not parts.get(check["only_if_nonzero"]):
            continue
        expected = sum(parts[k] for k in check["plus"]) - sum(parts[k] for k in check["minus"])
        if abs(expected - result) > tol:
            flags.append(_flag(f"{name}.{check['name']}", check,
                               f"{check['problem']} (server says {result}, formula gives {expected})"))
    return flags


def _breakdown_flag(card: dict, name: str) -> list[ValidationFlag]:
    items = schema.field(card, "category_breakdown")
    rewards = schema.number(card, "rewards")
    if not isinstance(items, list) or not items or not rewards:
        return []
    total = sum(schema.money(schema.field(i, "breakdown_value")) or 0 for i in items)
    tol = max(_CFG["rounding_tolerance"], rewards * 0.01)
    if abs(total - rewards) > tol and abs(total * 12 - rewards) <= tol:
        cfg = _CFG["breakdown_period"]
        return [_flag(f"{name}.category_breakdown", cfg,
                      f"{cfg['problem']} (breakdown {total:g}, x12 = {total * 12:g}, annual rewards {rewards})")]
    return []


def _income_flag(card: dict, name: str) -> list[ValidationFlag]:
    lpa = schema.money(schema.field(card, "salaried_lpa"))
    monthly = schema.number(card, "min_income_monthly")
    if not lpa or not monthly:
        return []
    if monthly >= rules["eligibility"]["monthly_looks_yearly_share"] * lpa * schema.LPA_UNIT:
        cfg = _CFG["monthly_looks_yearly"]
        return [_flag(f"{name}.eligibility", cfg, f"{cfg['problem']} ({lpa:g} LPA, but minimum monthly says {monthly})")]
    from_lpa = lpa * schema.LPA_UNIT / 12
    cfg = _CFG["income_consistency"]
    if abs(from_lpa - monthly) / monthly > cfg["tolerance"]:
        return [_flag(f"{name}.eligibility", cfg,
                      f"{cfg['problem']} ({lpa:g} LPA = {round(from_lpa)} a month, but minimum monthly says {monthly})")]
    return []


def _name_flag(card: dict, name: str, known_names: dict[str, str]) -> list[ValidationFlag]:
    alias = schema.card_id(card)
    listed = known_names.get(alias) if alias else None
    if not listed:
        return []
    shown, canonical = set(_WORD_RE.findall(name.lower())), set(_WORD_RE.findall(listed.lower()))
    if shown <= canonical:
        return []
    cfg = _CFG["name_mismatch"]
    return [_flag(f"{name}.name", cfg, f"{cfg['problem']} ('{name}' vs '{listed}', alias {alias})")]


def milestone_heavy(card: dict) -> bool:
    """True when the milestone benefit is more than the set share of the card's total value."""
    milestone = schema.number(card, "milestone") or 0
    total = milestone + (schema.number(card, "rewards") or 0) + (schema.number(card, "lounge") or 0)
    return milestone > 0 and milestone > _CFG["milestone_heavy"]["share"] * total


def _milestone_flag(card: dict, name: str) -> list[ValidationFlag]:
    if not milestone_heavy(card):
        return []
    cfg = _CFG["milestone_heavy"]
    return [_flag(f"{name}.milestone", cfg,
                  f"{cfg['problem']} (milestone {schema.number(card, 'milestone')}, rewards {schema.number(card, 'rewards')})")]


def validate_tool_output(raw: Any, known_names: dict[str, str] | None = None) -> list[ValidationFlag]:
    """known_names: alias -> name in the card list (for the name mismatch check)."""
    error = schema.error_of(raw)
    if error:
        return [ValidationFlag(field="response", problem=f"server returned error: {error}", suspected_fault="data")]

    cards = schema.cards_in(raw)
    flags: list[ValidationFlag] = []
    for card in cards:
        name = schema.card_label(card)
        flags += _fee_flags(card, name)
        flags += _formula_flags(card, name)
        flags += _breakdown_flag(card, name)
        flags += _income_flag(card, name)
        flags += _name_flag(card, name, known_names or {})
        flags += _milestone_flag(card, name)

    savings = [schema.number(c, "net_savings") for c in cards]
    if savings and all(s == 0 for s in savings):
        flags.append(_flag("response.ranking", _CFG["zero_ranking"]))
    return flags
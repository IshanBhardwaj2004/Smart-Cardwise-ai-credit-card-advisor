"""
Mock server: same response format as the real Great.cards server (₹ text, recommendations
list, card_alias, fees.joining...) with sample cards. For testing without network.

It copies the issues found on the real server, so the validator can be tested:
  - net savings does not subtract the joining fee (the description says it does)
  - the category breakdown "annual_value" is really monthly
  - empty spending still returns a ranking (all ₹0)
And in the sample cards:
  - Great Premium Plus: net savings math is wrong (mcp_tool)
  - Great Fuel Saver: LPA and monthly minimum income disagree (data)
  - Great Travel Elite: name spelled differently in recommend (data)
"""
from __future__ import annotations

from app.mcp import schema

_FMT = schema.format_inr

# rates: spending key -> reward rate (on yearly spend); "default" for everything else
_CARDS = [
    {"alias": "great-cashback-card", "name": "Great Cashback Card", "bank": "Great Bank",
     "joining": 0, "annual": 590, "waive_at": 100000, "lpa": (3, 3.5), "monthly_min": 25000,
     "rates": {"amazon_spends": 0.05, "flipkart_spends": 0.05, "other_online_spends": 0.05, "default": 0.01},
     "benefits": ["5% cashback on online spends", "1% cashback on offline spends"]},
    {"alias": "great-travel-elite", "name": "Great Travel Elite", "rec_name": "Great Travel Elit", "bank": "Great Bank",
     "joining": 5900, "annual": 5900, "lpa": (9, 12), "monthly_min": 75000, "milestone": (300000, 5000),
     "rates": {"flights_annual": 0.06, "hotels_annual": 0.06, "dining_or_going_out": 0.04, "default": 0.015},
     "benefits": ["6% value on flights and hotels", "8 domestic lounge visits a year"]},
    {"alias": "great-fuel-saver", "name": "Great Fuel Saver", "bank": "Fuel Bank",
     "joining": 499, "annual": 499, "waive_at": 50000, "lpa": (2.5, 3), "monthly_min": 30000,
     "rates": {"fuel": 0.05, "default": 0.01},
     "benefits": ["5% value back on fuel", "1% fuel surcharge waiver"]},
    {"alias": "great-premium-plus", "name": "Great Premium Plus", "bank": "Great Bank",
     "joining": 11800, "annual": 11800, "lpa": (15, 18), "monthly_min": 125000, "net_error": 3000,
     "rates": {"dining_or_going_out": 0.05, "flights_annual": 0.05, "hotels_annual": 0.05, "default": 0.02},
     "benefits": ["5% on dining and travel", "Unlimited lounge access"]},
]
_BRANDS = {"myntra": "other_online_spends", "dmart": "offline_grocery", "uber": "other_online_spends",
           "bookmyshow": "other_online_spends", "starbucks": "dining_or_going_out"}


def _fee(amount: int) -> str:
    return "Free" if amount == 0 else f"₹{_FMT(amount)} (incl. GST)"


def _find(alias):
    return next((c for c in _CARDS if c["alias"] == alias), None)


def _list_item(c):
    return {"name": c["name"], "bank": "", "joining_fee": _fee(c["joining"]),
            "annual_fee": _fee(c["annual"]), "card_alias": c["alias"]}


def _details(c, with_monthly=True):
    elig = {"min_age": 21, "max_age": 65, "income_salaried_lpa": c["lpa"][0], "income_self_emp_lpa": c["lpa"][1]}
    if with_monthly:
        elig["min_income_monthly"] = c["monthly_min"]
    fees = {"joining": _fee(c["joining"]), "annual": _fee(c["annual"])}
    if c.get("waive_at"):
        fees["annual_fee_waiver"] = f"The annual fee is waived if you spend ₹{_FMT(c['waive_at'])} or more in a year."
    return {"name": c["name"], "card_alias": c["alias"], "bank": c["bank"], "fees": fees,
            "key_benefits": [{"title": b, "description": ""} for b in c["benefits"]], "eligibility": elig}


def _recommend(args: dict) -> dict:
    spends = {k: v for k, v in args.items() if isinstance(v, (int, float)) and k not in ("top_n",)}
    yearly = {k: (v if schema.key_unit(k) == "year" else v * 12) for k, v in spends.items()}
    total = sum(yearly.values())
    rows = []
    for c in _CARDS:
        per_key = {k: v * c["rates"].get(k, c["rates"]["default"]) for k, v in yearly.items()}
        rewards = round(sum(per_key.values()))
        milestone = c["milestone"][1] if c.get("milestone") and total >= c["milestone"][0] else 0
        waived = bool(c.get("waive_at")) and total >= c["waive_at"]
        annual = 0 if waived else c["annual"]
        net = rewards + milestone - annual + c.get("net_error", 0)   # joining fee not subtracted (same as the real server)
        annual_text = f"Free (waived at ₹{_FMT(c['waive_at'])}/yr spend; {_fee(c['annual'])} otherwise)" if waived else _fee(c["annual"])
        top = sorted(per_key.items(), key=lambda kv: -kv[1])[:3]
        rows.append({
            "card_name": c.get("rec_name", c["name"]), "bank_name": c["bank"],
            "net_annual_savings": f"₹{_FMT(net)}", "annual_rewards_value": f"₹{_FMT(rewards)}",
            "milestone_benefits": f"₹{_FMT(milestone)}", "lounge_value": "₹0",
            "joining_fee": _fee(c["joining"]), "annual_fee": annual_text, "annual_fee_waived": waived,
            # same as the real server: named "annual_value" but holds the monthly value
            "top_spend_categories": [{"category": k, "annual_value": f"₹{_FMT(v / 12)}"} for k, v in top],
            "card_alias": c["alias"], "_net": net,
        })
    rows.sort(key=lambda r: -r["_net"])
    top_n = int(args.get("top_n", 5))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        del r["_net"]
    return {"total_cards_analyzed": len(_CARDS), "recommendations": rows[:top_n],
            "_format_hint": "net_annual_savings = annual_rewards + milestone_benefits + lounge_value - annual_fee."}


def _eligibility(args: dict) -> dict:
    income = float(str(args.get("annual_income", "0")).replace(",", "") or 0)
    idx = 0 if args.get("employment_status") == "salaried" else 1
    ok = [c for c in _CARDS if income >= c["lpa"][idx] * schema.LPA_UNIT]
    return {"eligible_cards_count": len(ok),
            "profile": {"pincode": args.get("pincode"), "annual_income": f"₹{_FMT(income)}",
                        "employment": args.get("employment_status")},
            "eligible_cards": [_list_item(c) for c in ok]}


def _resolve(phrase: str) -> dict:
    words = str(phrase).lower()
    for brand, key in _BRANDS.items():
        if brand in words:
            return {"reply_type": "resolution", "best_match": {"type": "brand", "brand": brand,
                    "spending_key": key, "confidence": "high", "needs_clarification": False}}
    return {"reply_type": "resolution", "matches": [], "best_match": None}


def call(tool: str, args: dict):
    """Mock tools/call (in the real server's format)."""
    A = schema.ARGS
    if tool == schema.TOOL_RECOMMEND:
        return _recommend(args)
    if tool == schema.TOOL_LIST_CARDS:
        return {"total_available": len(_CARDS), "showing": len(_CARDS), "cards": [_list_item(c) for c in _CARDS]}
    if tool == schema.TOOL_CARD_DETAILS:
        card = _find(args.get(A["card_alias"]))
        return _details(card) if card else {"error": "card not found"}
    if tool == schema.TOOL_COMPARE:
        found = [_find(a) for a in args.get(A["card_aliases"], [])]
        return {"comparison": [_details(c, with_monthly=False) for c in found if c]}
    if tool == schema.TOOL_CHECK_ELIGIBILITY:
        return _eligibility(args)
    if tool == schema.TOOL_RESOLVE:
        return _resolve(args.get(A["phrase"], ""))
    return {"error": f"unknown tool {tool}"}
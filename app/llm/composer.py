"""
Step 11 + 12: get the reply from the LLM, then check it with the output guard.
If it fails (or the LLM is down): one retry, then a plain-English reply built from the data.
"""
from __future__ import annotations

from app.config import rules
from app.guards.output_guard import check_output
from app.mcp.schema import format_inr, money

_MSG = rules["messages"]
_R = rules["replies"]


def _short(value) -> str:
    """'₹1,180 (incl. GST)' -> '₹1,180'; 'HDFC Millennia Credit Card' -> 'HDFC Millennia'.
    The full text stays on the card shown below the reply."""
    text = str(value).split(" (")[0].strip()
    for tail in _R["short_name_drop"]:
        if text.endswith(tail) and len(text) > len(tail):
            return text[: -len(tail)].strip()
    return text


def _name(card: dict) -> str:
    return _short(card["card_name"])


def _join(items: list[str]) -> str:
    """["A", "B", "C"] -> "A, B and C" """
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + _R["list_join"] + items[-1]


def _fees(cards: list[dict], key: str = "joining_fee") -> str:
    return _join([_R["fee_item"].format(card=_name(c), fee=_short(c[key])) for c in cards if c.get(key)])


def _recommend(data: dict, cards: list[dict]) -> str:
    top = cards[0]
    tied_names = data.get("top_cards_tied")
    if tied_names:
        tied = [c for c in cards if c["card_name"] in tied_names]
        text = _R["tied"].format(cards=_join([_name(c) for c in tied]), net=top.get("net_savings"), fees=_fees(tied))
        free = [c for c in tied if money(c.get("joining_fee")) == 0]
        if free and len(free) < len(tied):
            text += _R["tied_pick"].format(card=_name(free[0]))
        return text

    if (money(top.get("net_savings")) or 0) <= 0:
        return _R["no_value"].format(card=_name(top), net=top.get("net_savings"))

    total = (data.get("user_profile") or {}).get("total_annual_spend")
    text = (_R["recommend_with_total"].format(total=format_inr(total), card=_name(top), net=top.get("net_savings"))
            if total else _R["recommend"].format(card=_name(top), net=top.get("net_savings")))
    if top.get("invite_only"):
        text += _R["invite_only"].format(card=_name(top))
    if top.get("milestone_overvalued") and top.get("milestone"):
        return text + _R["milestone_overvalued"].format(milestone=top["milestone"])
    if top.get("mostly_milestone") and top.get("milestone"):
        # the milestone caveat matters more than the runner-up, so keep the reply short
        return text + _R["milestone_heavy"].format(milestone=top["milestone"])
    if money(top.get("joining_fee")):
        text += _R["joining_fee"].format(fee=_short(top["joining_fee"]))
    if len(cards) > 1 and cards[1].get("net_savings"):
        text += _R["runner_up"].format(card=_name(cards[1]), net=cards[1]["net_savings"])
    return text


def _eligibility_card(v: dict) -> str:
    if v.get("required_monthly_income") is None:
        return _R["eligibility_unknown"].format(card=_short(v["card_name"]))
    need = f"₹{format_inr(v['required_monthly_income'])} a month"
    text = _R["eligibility_meets" if v["meets_income"] else "eligibility_short"].format(card=_short(v["card_name"]), need=need)
    y = v.get("monthly_minimum_looks_yearly")
    if y:
        text += _R["eligibility_yearly_in_monthly"].format(listed=format_inr(y["listed_monthly"]),
                                                           used=format_inr(y["read_as_monthly"]))
    d = v.get("card_data_disagrees")
    if d:
        text += _R["eligibility_disagree"].format(a=format_inr(d["minimum_from_lpa_per_month"]),
                                                  b=format_inr(d["minimum_monthly"]))
    return text


def template_reply(data: dict) -> str:
    """A short, human reply that uses only names and numbers from the data (no LLM)."""
    kind, cards = data.get("kind"), data.get("cards") or []
    if kind == "eligibility_card":
        return _eligibility_card(data["verdict"])
    if not cards:
        return _MSG["no_data"]
    if kind == "eligibility_list":
        text = _R["eligibility_list"]
        left_out = data.get("left_out_over_income")
        if left_out:
            text += _R["eligibility_removed"].format(n=len(left_out), cards=_join([_short(c) for c in left_out]))
        return text
    if kind == "card_details":
        c = cards[0]
        text = _R["card_details"].format(card=_name(c), joining=_short(c.get("joining_fee", "?")),
                                  annual=_short(c.get("annual_fee", "?")))
        if c.get("fee_waiver_note"):
            text += _R["card_details_waiver"].format(waiver=c["fee_waiver_note"])
        return text
    if kind == "compare":
        return _R["compare"].format(cards=_join([_name(c) for c in cards]), fees=_fees(cards, "annual_fee"))
    return _recommend(data, cards)


def compose_answer(user_message: str, data: dict, llm, trace) -> tuple[str, bool]:
    """Return: (reply text, whether the template reply was used instead of the LLM)"""
    for attempt in (1, 2):
        try:
            reply = llm.compose(user_message, data)
        except Exception as e:
            # type name too: a timeout's message is often empty
            trace.note(f"LLM compose failed: {type(e).__name__}: {e}")
            break
        if attempt == 1:
            trace.llm_raw_reply = reply
        guard = check_output(reply, data)
        trace.output_guard = guard
        if guard["ok"]:
            return reply, False
        trace.note(f"output guard failed on attempt {attempt}: {guard['problems']}")

    trace.note("no safe LLM reply, using the plain template reply instead")
    return template_reply(data), True

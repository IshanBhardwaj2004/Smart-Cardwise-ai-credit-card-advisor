"""
Eligibility workflow, two ways:
  - A card is named ("am I eligible for HDFC Regalia?"):
    fetch that card's details and compare its minimum income with the user's income
    in CODE. check_eligibility returns only part of its list, so the card details
    are the reliable way to check one specific card.
  - No card named ("which cards can I get?"):
    check_eligibility (pincode + annual income + job type).
The verdict is always "may be eligible", never certain; the bank decides.
"""
from __future__ import annotations

from app.config import rules
from app.core.models import ToolCallRecord
from app.mcp import schema
from app.mcp.client import MCPClient
from app.workflows.card_details import fetch

_CFG = rules["eligibility"]
_LPA_FIELD = _CFG["lpa_field_by_employment"]      # job type -> which LPA field
_DEFAULT_EMPLOYMENT = _CFG["default_employment"]  # used when the job type is not given


def verdict(details: dict, monthly_income: int, employment: str | None) -> dict:
    """Card's minimum income vs the user's income. Every number comes from the server or the user."""
    used = employment or _DEFAULT_EMPLOYMENT
    lpa = schema.money(schema.field(details, _LPA_FIELD.get(used, _LPA_FIELD[_DEFAULT_EMPLOYMENT])))
    monthly_min = schema.number(details, "min_income_monthly")
    from_lpa = round(lpa * schema.LPA_UNIT / 12) if lpa else None

    # a "monthly" minimum close to the whole yearly minimum can't be monthly (e.g. 4 LPA but
    # 4,00,000 a month): read it as a yearly amount instead of telling the user they need 12x more
    yearly_in_monthly = None
    if lpa and monthly_min and monthly_min >= _CFG["monthly_looks_yearly_share"] * lpa * schema.LPA_UNIT:
        yearly_in_monthly = {"listed_monthly": monthly_min, "read_as_monthly": round(monthly_min / 12)}
        monthly_min = round(monthly_min / 12)

    # if both minimums exist, use the higher (stricter) one so we don't raise false hopes
    needed = [x for x in (from_lpa, monthly_min) if x]
    required_monthly = int(max(needed)) if needed else None

    result = {
        "card_name": schema.card_label(details),
        "employment_used": used,
        "employment_assumed": employment is None,
        "your_monthly_income": monthly_income,
        "required_monthly_income": required_monthly,
        "required_lpa": lpa,
        "meets_income": None if required_monthly is None else monthly_income >= required_monthly,
        "min_age": schema.field(details, "min_age"),
        "max_age": schema.field(details, "max_age"),
    }
    if yearly_in_monthly:
        result["monthly_minimum_looks_yearly"] = yearly_in_monthly
    # if the card's own two rules disagree, tell the user (don't hide it)
    if from_lpa and monthly_min and abs(from_lpa - monthly_min) > 1:
        result["card_data_disagrees"] = {"minimum_from_lpa_per_month": from_lpa, "minimum_monthly": monthly_min}
    return result


def run(slots, mcp: MCPClient, trace):
    if slots.card_ids:
        trace.workflow = "eligibility_card"
        if slots.monthly_income is None:
            return {"_need": "income"}
        details = fetch(slots.card_ids[0], mcp, trace)
        if schema.error_of(details):
            return details
        return {"details": details, "verdict": verdict(details, slots.monthly_income, slots.employment)}

    trace.workflow = "eligibility_list"
    for need, value in (("income", slots.monthly_income), ("employment", slots.employment), ("pincode", slots.pincode)):
        if value is None:
            return {"_need": need}
    A = schema.ARGS
    args = {A["pincode"]: slots.pincode,
            A["annual_income"]: str(slots.monthly_income * 12),
            A["employment_status"]: slots.employment}
    raw = mcp.call(schema.TOOL_CHECK_ELIGIBILITY, args)
    trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_CHECK_ELIGIBILITY, arguments=args, raw_response=raw, ok=True))
    return raw
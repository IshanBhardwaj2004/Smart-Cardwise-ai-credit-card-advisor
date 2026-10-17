"""
Pipeline: runs the whole flow in order. It does no calculation itself; it calls
each step and records everything in the trace.

Session: if the bot asked something (income, pincode...), the next short reply
("50k", "110001") is taken as the answer and merged with what was said before.
A new question clears the old one.
Messages and limits: rules.json
"""
from __future__ import annotations

from collections import OrderedDict

from app.config import config, rules
from app.core.models import CardView, ChatReply, Intent, Meter, Metric, Slots, ToolCallRecord
from app.guards.input_guard import check_input
from app.llm.client import LLMClient
from app.llm.composer import compose_answer
from app.mcp import schema
from app.mcp.client import MCPClient, MCPError
from app.nlu.clarify import missing_info, question_for
from app.nlu.intent import _keyword_intent, resolve_intent
from app.nlu.slots import extract_slots, to_spend
from app.trace.store import save_trace
from app.trace.trace import Trace
from app.validation.tool_validator import milestone_heavy, validate_tool_output
from app.workflows.name_resolver import card_index, find_cards_in_text
from app.workflows.router import route

_MSG = rules["messages"]
_UI = rules["ui"]
_LLM = rules["llm"]
_RESOLVER = rules["mcp"]["resolver"]

# intents that need card names from the message
_CARD_INTENTS = {Intent.CARD_DETAILS, Intent.COMPARE, Intent.ELIGIBILITY}


class _Sessions:
    """Unfinished work per session: {intent, slots, expecting}. In memory, with a size limit."""

    def __init__(self, limit: int):
        self._data: OrderedDict = OrderedDict()
        self._limit = limit

    def get(self, sid):
        return self._data.get(sid) if sid else None

    def put(self, sid, intent: Intent, slots: Slots, expecting: str):
        if not sid:
            return
        self._data[sid] = {"intent": intent, "slots": slots, "expecting": expecting}
        self._data.move_to_end(sid)
        while len(self._data) > self._limit:
            self._data.popitem(last=False)

    def clear(self, sid):
        self._data.pop(sid, None)


class Pipeline:
    def __init__(self, llm: LLMClient | None = None, mcp: MCPClient | None = None):
        self.llm = llm or LLMClient()
        self.mcp = mcp or MCPClient()
        self.sessions = _Sessions(rules["session"]["max_sessions"])

    def handle(self, message: str, session_id: str | None = None) -> ChatReply:
        trace = Trace(message, session_id)   # the trace redacts card numbers, PAN and similar data
        try:
            try:
                reply = self._run(trace, message)
            except MCPError as e:
                # server unreachable: don't guess, say so
                trace.note(f"MCP failure: {e}")
                reply = _reply(trace, _MSG["service_down"], trace.intent or Intent.UNKNOWN)
            trace.final_reply = reply.reply
            return reply
        finally:
            save_trace(trace, config.TRACE_DIR)

    # ---------------- main flow ----------------
    def _run(self, trace: Trace, msg: str) -> ChatReply:
        sid = trace.session_id

        # 1. input guard: tax / approval / off-topic requests stop here
        guard = check_input(msg)
        trace.input_guard = guard.model_dump()
        if guard.blocked:
            self.sessions.clear(sid)
            trace.intent = Intent.REFUSE
            return _reply(trace, guard.user_message, Intent.REFUSE, refused=True)

        # 2. intent (if the bot asked something and no new intent shows up, continue that one)
        pending = self.sessions.get(sid)
        intent = self._intent(msg, pending, trace)
        if pending and intent != pending["intent"]:
            pending = None
        trace.intent = intent
        if intent in (Intent.REFUSE, Intent.UNKNOWN):
            self.sessions.clear(sid)
            return _reply(trace, _MSG["help"], intent, clarifying=True)

        # 3. slots + 4. card names (from the server's list), then merge with earlier answers
        slots = extract_slots(msg, pending["expecting"] if pending else None,
                              bare_pincode_ok=intent == Intent.ELIGIBILITY)
        if intent in _CARD_INTENTS:
            found = find_cards_in_text(msg, self.mcp, trace)
            unclear = next((f for f in found if f["alternatives"]), None)
            if unclear:
                options = [unclear["card_name"], *unclear["alternatives"]]
                return self._ask(trace, intent, slots, "card", _MSG["which_one"].format(options=" or ".join(options)))
            slots.card_names = [f["card_name"] for f in found]
            slots.card_ids = [f["card_id"] for f in found]
        if pending:
            slots = _merge(pending["slots"], slots)
        if intent == Intent.RECOMMEND:
            self._resolve_loose_amounts(slots, trace)
        trace.slots = slots

        # 5. clarify: if required info is missing, ask one question (and remember what was asked)
        mode = _mode(intent, slots)
        missing = missing_info(mode, slots)
        if missing:
            return self._ask(trace, intent, slots, *missing)

        # 6-9. router + workflow + MCP call (raw response saved in the trace)
        result = route(intent, slots, self.mcp, trace)
        if isinstance(result, dict) and "_need" in result:
            return self._ask(trace, intent, slots, result["_need"], question_for(result["_need"]))
        self.sessions.clear(sid)
        mode = trace.workflow or mode
        raw = result.get("details") if mode == "eligibility_card" and isinstance(result, dict) else result

        # 10. validator: check data before the LLM (all flags kept in the trace as evidence)
        names = self._known_names(trace)
        flags = validate_tool_output(raw, names)
        trace.validation_flags = flags
        shown = _shown_cards(mode, raw)
        suspect = _is_suspect(flags, shown)

        if mode == "recommend" and shown and all(schema.number(c, "net_savings") == 0 for c in shown):
            # all ₹0: the ranking means nothing, so don't recommend
            return _reply(trace, _MSG["no_savings"], intent, clarifying=True, suspect_data=True)

        # 11-12. LLM reply + output guard (retry / fallback handled inside)
        data = _llm_data(mode, raw, result, slots, shown, names)
        trace.validated_data = data
        text, used_fallback = compose_answer(msg, data, self.llm, trace)

        # tell the user when they ask to compare more cards than the server allows
        limit = schema.OPTIONS["max_compare"]
        if mode == "compare" and len(slots.card_ids) > limit:
            text = _MSG["compare_limit"].format(n=limit) + " " + text

        flagged = {f.field.rsplit(".", 1)[0] for f in flags if f.warn_user}
        return _reply(
            trace, text, intent,
            cards=_card_views(mode, shown, result, flagged, names),
            # the bank note matters only when we talk about eligibility
            note=_MSG["bank_note"] if mode.startswith("eligibility") else None,
            warning=_MSG["suspect_note"] if suspect else None,
            meter=_meter(result["verdict"]) if mode == "eligibility_card" else None,
            mode=mode, fallback_table=used_fallback, suspect_data=suspect,
        )

    # ---------------- helpers (methods) ----------------
    def _intent(self, msg: str, pending, trace: Trace) -> Intent:
        keyword, _ = _keyword_intent(msg)
        if keyword is None and pending:
            trace.intent_source = "session"
            trace.note(f"continuing {pending['intent'].value}, answer for '{pending['expecting']}'")
            return pending["intent"]
        if keyword is None:
            # "amazon 15k flipkart 5k": no keyword, but spending is clearly described
            probe = extract_slots(msg)
            if probe.spends or (probe.loose_amounts and probe.monthly_income is None):
                trace.intent_source = "spending"
                trace.note("intent recommend: message describes spending")
                return Intent.RECOMMEND
            # "sbi cashbak details": no keyword, but a card name from the server's list
            named = find_cards_in_text(msg, self.mcp, trace)
            if named:
                trace.intent_source = "card_name"
                return Intent.COMPARE if len(named) > 1 else Intent.CARD_DETAILS
        return resolve_intent(msg, self.llm, trace)

    def _ask(self, trace: Trace, intent: Intent, slots: Slots, missing: str, question: str) -> ChatReply:
        self.sessions.put(trace.session_id, intent, slots, missing)
        trace.slots = slots
        trace.clarify_question = question
        return _reply(trace, question, intent, clarifying=True)

    def _resolve_loose_amounts(self, slots: Slots, trace: Trace) -> None:
        """Ask the server's brand resolver about amounts whose category the code could not tell."""
        unresolved = []
        for loose in slots.loose_amounts:
            args = {schema.ARGS["phrase"]: loose.snippet}
            raw = self.mcp.call(schema.TOOL_RESOLVE, args)
            trace.add_tool_call(ToolCallRecord(tool=schema.TOOL_RESOLVE, arguments=args, raw_response=raw, ok=True))
            best = raw.get(_RESOLVER["best_match"]) if isinstance(raw, dict) else None
            key = best.get(_RESOLVER["spending_key"]) if isinstance(best, dict) else None
            if key and not best.get(_RESOLVER["needs_clarification"]):
                slots.spends = [s for s in slots.spends if s.key != key]
                slots.spends.append(to_spend(key, loose.amount, loose.period))
            else:
                unresolved.append(loose)
        slots.loose_amounts = unresolved

    def _known_names(self, trace: Trace) -> dict[str, str]:
        try:
            return card_index(self.mcp, trace)
        except MCPError as e:
            trace.note(f"card list unavailable for name check: {e}")
            return {}


# ---------------- helpers (pure) ----------------

def _reply(trace: Trace, text: str, intent: Intent, **extra) -> ChatReply:
    return ChatReply(reply=text, request_id=trace.request_id, intent=intent, **extra)


def _mode(intent: Intent, slots: Slots) -> str:
    if intent == Intent.ELIGIBILITY:
        return "eligibility_card" if slots.card_ids else "eligibility_list"
    return intent.value


def _merge(old: Slots, new: Slots) -> Slots:
    """Earlier info + new reply. Whatever the new reply says wins.
    If the category came in one message and the amount in another, pair them."""
    spends = {s.key: s for s in old.spends}
    spends.update({s.key: s for s in new.spends})

    # amounts without a category and categories without an amount (across both turns)
    amounts = new.loose_amounts or old.loose_amounts
    keys = new.mentioned_keys or old.mentioned_keys
    paired = 0
    if new.loose_amounts or new.mentioned_keys:      # only pair them when the new reply brought one of these
        for key, la in zip(keys, amounts):
            spends[key] = to_spend(key, la.amount, la.period)
            paired += 1

    return Slots(
        spends=list(spends.values()),
        loose_amounts=amounts[paired:],
        mentioned_keys=keys[paired:],
        card_names=new.card_names or old.card_names,
        card_ids=new.card_ids or old.card_ids,
        monthly_income=new.monthly_income if new.monthly_income is not None else old.monthly_income,
        employment=new.employment or old.employment,
        pincode=new.pincode or old.pincode,
    )


def _shown_cards(mode: str, raw) -> list[dict]:
    """Which cards are shown to the user."""
    cards = schema.cards_in(raw)
    limits = {"recommend": schema.OPTIONS["recommend_top_n"], "card_details": 1, "eligibility_card": 1,
              "compare": schema.OPTIONS["max_compare"], "eligibility_list": schema.OPTIONS["eligible_cards_shown"]}
    return cards[:limits.get(mode, 0)]


def _is_suspect(flags, shown: list[dict]) -> bool:
    """Warn only when a shown card (or the whole response) has a problem that matters to the user."""
    names = {schema.card_label(c) for c in shown}
    return any(f.warn_user and (f.field.startswith("response") or f.field.rsplit(".", 1)[0] in names or not shown)
               for f in flags)


def _display_name(card: dict, names: dict[str, str]) -> str:
    """Clean name from the card list (by alias), else what the server sent."""
    return names.get(schema.card_id(card)) or schema.card_label(card)


def _user_profile(slots: Slots) -> dict:
    profile = {}
    if slots.spends:
        profile["spends"] = [{"spending_key": s.key, "amount": s.amount, "per": s.unit, "per_year": s.annual_amount}
                             for s in slots.spends]
        profile["total_annual_spend"] = slots.total_annual_spend
    if slots.monthly_income is not None:
        profile["monthly_income"] = slots.monthly_income
        profile["annual_income"] = slots.monthly_income * 12
    if slots.employment:
        profile["employment"] = slots.employment
    return profile


def _compact_card(card: dict, names: dict[str, str]) -> dict:
    """Only the card fields the LLM needs, with server text as is."""
    out = {"card_name": _display_name(card, names)}
    for key in _LLM["card_fields"]:
        if key == "card_name":
            continue
        value = schema.field(card, key)
        if value is not None and not isinstance(value, (dict, list)):
            out[key] = value
    benefits = schema.benefit_titles(card, _LLM["max_benefits"])
    if benefits:
        out["benefits"] = benefits
    if milestone_heavy(card):
        out["mostly_milestone"] = True
    return out


def _llm_data(mode: str, raw, result, slots: Slots, shown: list[dict], names: dict[str, str]) -> dict:
    """Small, clean data for the LLM (Qwen 8B has a short context). The output guard checks against this."""
    data = {"kind": mode, "cards": [_compact_card(c, names) for c in shown]}
    profile = _user_profile(slots)
    if profile:
        data["user_profile"] = profile
    for key in ("cards_analyzed", "eligible_count"):
        value = schema.field(raw, key) if isinstance(raw, dict) else None
        if value is not None:
            data[key] = value
    if mode == "eligibility_card":
        data["verdict"] = result["verdict"]
    tied = _tied_top(mode, shown)
    if len(tied) > 1:
        data["top_cards_tied"] = [_display_name(c, names) for c in tied]
    return data


def _tied_top(mode: str, shown: list[dict]) -> list[dict]:
    """Top recommended cards with equal net savings (the server does not separate them by fees)."""
    if mode != "recommend" or not shown:
        return []
    top = schema.number(shown[0], "net_savings")
    return [c for c in shown if top is not None and schema.number(c, "net_savings") == top]


def _split(text: str) -> tuple[str, str | None]:
    """'₹1,180 (incl. GST)' -> ('₹1,180', 'incl. GST')"""
    if " (" in text and text.endswith(")"):
        head, tail = text.split(" (", 1)
        return head.strip(), tail[:-1].strip()
    return text, None


def _meter(v: dict) -> Meter | None:
    """Eligibility bar from the verdict (user's income and the card's minimum)."""
    need, you = v.get("required_monthly_income"), v.get("your_monthly_income")
    if not need or you is None:
        return None
    m = _UI["meter"]
    return Meter(title=m["title"], you=f"₹{schema.format_inr(you)}", needed=f"₹{schema.format_inr(need)}",
                 status=m["meets" if v["meets_income"] else "short"], meets=bool(v["meets_income"]),
                 fill=round(min(you / need, 1.0), 3))


def _card_views(mode: str, shown: list[dict], result, flagged: set[str], names: dict[str, str]) -> list[CardView]:
    """UI cards: metrics from rules.json -> ui.card_metrics, values from server text.
    flagged: cards whose data has a user-facing problem (they get no badge)."""
    metric_mode = "card_details" if mode == "eligibility_card" else mode
    keys = _UI["card_metrics"].get(metric_mode, [])
    tied = len(_tied_top(mode, shown)) > 1   # with equal savings, no single card is called "best"
    views = []
    for i, card in enumerate(shown):
        metrics = []
        for key in keys:
            value = schema.text(card, key)
            if value is None or (key in _UI["hide_if_zero"] and schema.money(value) == 0):
                continue
            main, detail = _split(value)
            metrics.append(Metric(key=key, label=_UI["labels"][key], value=main, detail=detail,
                                  highlight=key == "net_savings" and (schema.money(value) or 0) > 0))
        badge = None
        if (mode == "recommend" and i == 0 and not tied and (schema.number(card, "net_savings") or 0) > 0
                and schema.card_label(card) not in flagged and "response" not in flagged):
            badge = _MSG["best_badge"]
        elif mode == "eligibility_card" and result["verdict"].get("meets_income"):
            badge = _MSG["eligible_badge"]
        benefits = schema.benefit_titles(card, _LLM["max_benefits"]) if metric_mode == "card_details" else []
        tags = [_UI["labels"]["free_join"]] if schema.money(schema.text(card, "joining_fee")) == 0 else []
        views.append(CardView(name=_display_name(card, names), alias=schema.card_id(card),
                              badge=badge, metrics=metrics, benefits=benefits, tags=tags))
    return views
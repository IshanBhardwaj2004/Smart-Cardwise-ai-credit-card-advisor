"""
MCP server explore script (diagnostic, not part of the app).
Saves every tool's full description, and calls each important tool once in the
right format, saving the full response to mcp_snapshot.json.
About 11 calls, not a load test.

It also has lookups to check the bot's answers against the server directly:
  python -m evals.explore_mcp cards hdfc
  python -m evals.explore_mcp card "hdfc regalia"
  python -m evals.explore_mcp spend amazon_spends=15000
  python -m evals.explore_mcp export
Run without arguments for the snapshot, or with "help" for usage.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.mcp import schema  # noqa: E402
from app.mcp.client import MCPClient  # noqa: E402
from app.trace.trace import Trace  # noqa: E402
from app.workflows.name_resolver import card_list, find_cards_in_text  # noqa: E402

OUT = "mcp_snapshot.json"


def shape(value, depth=0):
    """Short summary of a response: keys and list lengths."""
    if isinstance(value, dict):
        if depth >= 1:
            return f"{{{len(value)} keys}}"
        return {k: shape(v, depth + 1) for k, v in list(value.items())[:25]}
    if isinstance(value, list):
        return f"list[{len(value)}]" + (f" of {shape(value[0], depth + 1)}" if value else "")
    text = str(value)
    return text if len(text) <= 60 else text[:60] + "..."


def main():
    mcp = MCPClient()
    snap = {"server": mcp.url, "tools": [], "calls": {}}

    try:
        snap["tools"] = mcp.describe_tools()
        print(f"Saved full descriptions of {len(snap['tools'])} tools.")
    except Exception as e:
        print(f"Could not list tools: {e}")

    def probe(label, tool, args):
        try:
            result = mcp.call(tool, args)
        except Exception as e:
            result = {"call_failed": str(e)}
        snap["calls"][label] = {"tool": tool, "arguments": args, "response": result}
        print(f"\n=== {label} ({tool}) ===")
        print(json.dumps(shape(result), ensure_ascii=False, indent=2)[:1500])
        return result

    probe("advisor_context", "get_advisor_context", {"topic": "full"})

    cards = probe("list_cards_all", "list_cards", {"limit": 300, "response_format": "brief"})
    aliases = []
    if isinstance(cards, dict):
        for v in cards.values():
            if isinstance(v, list):
                aliases = [c.get("card_alias") for c in v if isinstance(c, dict) and c.get("card_alias")]
                break
    print(f"\nCards found: {len(aliases)}")

    first = aliases[0] if aliases else "hdfc-regalia-gold-credit-card"
    second = aliases[1] if len(aliases) > 1 else "axis-magnus-credit-card"

    probe("card_details", "get_card_details", {"card_alias": first})
    probe("recommend_single", "recommend_cards",
          {"amazon_spends": 15000, "top_n": 3, "response_format": "full"})
    probe("recommend_mixed", "recommend_cards",
          {"dining_or_going_out": 20000, "flights_annual": 150000, "fuel": 5000,
           "top_n": 3, "response_format": "full"})
    probe("recommend_empty", "recommend_cards", {"top_n": 3})
    probe("compare", "compare_cards", {"card_aliases": [first, second]})
    probe("eligibility", "check_eligibility",
          {"pincode": "110001", "annual_income": "600000", "employment_status": "salaried"})
    probe("resolve_card", "whatsapp_resolve_card_or_category", {"phrase": "hdfc regaliaa"})
    probe("resolve_category", "whatsapp_resolve_card_or_category", {"phrase": "swiggy and zomato"})
    probe("category_spend", "whatsapp_recommend_cards_for_category_spend",
          {"category": "fuel", "amount": 10000, "top_n": 3})

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    print(f"\nEverything saved to {OUT} ({os.path.getsize(OUT) // 1024} KB). Please share this file.")


# ---------- lookups: ask the server directly, without the bot ----------

def _save(name: str, data) -> None:
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nFull response saved to {name}")


def find_cards(words: str) -> None:
    """List cards whose name or alias contains every given word."""
    mcp = MCPClient()
    trace = Trace(words)
    wanted = words.lower().split()
    hits = [c for c in card_list(mcp, trace)
            if all(w in f"{schema.card_label(c)} {schema.card_id(c)}".lower() for w in wanted)]
    print(f"{len(hits)} card(s) match '{words}':\n")
    for c in hits:
        print(f"  {schema.card_label(c)}")
        print(f"      alias: {schema.card_id(c)} | joining: {schema.text(c, 'joining_fee')} | annual: {schema.text(c, 'annual_fee')}")


def card_details(query: str) -> None:
    """Full details of one card. Accepts an alias or a card name (typos allowed)."""
    mcp = MCPClient()
    alias = query if "-" in query and " " not in query else None
    if not alias:
        found = find_cards_in_text(query, mcp, Trace(query))
        if not found:
            print(f"No card matches '{query}'. Try: python -m evals.explore_mcp cards <word>")
            return
        alias = found[0]["card_id"]
    d = mcp.call(schema.TOOL_CARD_DETAILS, {schema.ARGS["card_alias"]: alias})
    if schema.error_of(d):
        print(f"Server error: {schema.error_of(d)}")
        return

    print(f"\n{schema.card_label(d)}   (alias: {alias})")
    print(f"  Joining fee : {schema.text(d, 'joining_fee')}")
    print(f"  Annual fee  : {schema.text(d, 'annual_fee')}")
    print(f"  Fee waiver  : {schema.text(d, 'fee_waiver_note')}")
    elig = d.get("eligibility") or {}
    print("  Eligibility : " + ", ".join(f"{k}={v}" for k, v in elig.items()))
    print("  Key benefits:")
    for b in d.get("key_benefits") or []:
        print(f"    - {b.get('title', '')}: {b.get('description', '')}")
    rewards = d.get("rewards") or {}
    if rewards.get("exclusions"):
        print(f"  No rewards on: {rewards['exclusions']}")
    for key in ("annual_saving_claimed", "existing_customer_only", "invite_only", "employment_type"):
        if key in d:
            print(f"  {key}: {d[key]}")
    _save(f"card_{alias}.json", d)


def spend_check(pairs: list[str]) -> None:
    """recommend_cards for the given spending (key=value), with the math checked for each card."""
    args = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        args[key.strip()] = float(value)
    args.update({schema.ARGS["top_n"]: 5, schema.ARGS["response_format"]: "full"})
    raw = MCPClient().call(schema.TOOL_RECOMMEND, args)
    cards = schema.cards_in(raw)
    print(f"Sent: {args}\nCards analysed: {schema.field(raw, 'cards_analyzed')}\n")
    for c in cards:
        n = {k: schema.number(c, k) or 0 for k in ("net_savings", "rewards", "milestone", "lounge", "joining_fee", "annual_fee")}
        hint = n["rewards"] + n["milestone"] + n["lounge"] - n["annual_fee"]
        described = hint - n["joining_fee"]
        print(f"  #{c.get('rank')} {schema.card_label(c)}")
        print(f"      net {n['net_savings']} = rewards {n['rewards']} + milestone {n['milestone']} + lounge {n['lounge']}"
              f" - annual fee {n['annual_fee']}  ->  {'OK' if abs(hint - n['net_savings']) <= 1 else 'MISMATCH (' + str(hint) + ')'}")
        print(f"      joining fee {n['joining_fee']} (if subtracted as the tool description says: {described})")
    _save("spend_result.json", raw)


def _flat(value, prefix: str = "", out: dict | None = None) -> dict:
    """Nested response as flat columns: {"fees": {"joining": x}} -> {"fees.joining": x}.
    Lists of objects become one text cell, e.g. "title: description | title: description"."""
    out = {} if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            _flat(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(": ".join(str(v) for v in item.values() if v not in (None, "")))
            elif item not in (None, ""):
                parts.append(str(item))
        out[prefix] = " | ".join(parts)
    else:
        out[prefix] = value
    return out


def export_all(out_json: str = "all_cards.json", out_csv: str = "all_cards.csv") -> None:
    """Full details of every card in one file. Safe to stop and rerun: cards already saved are skipped."""
    import csv
    import time

    mcp = MCPClient()
    cards = card_list(mcp, Trace("export"))
    saved = {}
    if os.path.exists(out_json):
        with open(out_json, encoding="utf-8") as f:
            saved = {c["card_alias"]: c for c in json.load(f) if c.get("card_alias")}
        print(f"{len(saved)} cards already in {out_json}, fetching the rest.")

    failed = []
    for i, c in enumerate(cards, 1):
        alias = schema.card_id(c)
        if not alias or alias in saved:
            continue
        try:
            d = mcp.call(schema.TOOL_CARD_DETAILS, {schema.ARGS["card_alias"]: alias})
        except Exception as e:
            d = {"error": str(e)}
        if schema.error_of(d):
            failed.append(alias)
            print(f"  [{i}/{len(cards)}] {alias}: failed ({schema.error_of(d)})")
        else:
            d.setdefault("card_alias", alias)
            saved[alias] = d
            print(f"  [{i}/{len(cards)}] {schema.card_label(d)}")
        if i % 20 == 0:  # save progress now and then, so a stop loses little
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(list(saved.values()), f, ensure_ascii=False, indent=2)
        time.sleep(0.2)  # be gentle with the server

    rows = list(saved.values())
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    flat = [_flat(r) for r in rows]
    columns = []
    for r in flat:
        columns += [k for k in r if k not in columns]
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig so Excel shows ₹ correctly
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(flat)

    print(f"\nSaved {len(rows)} cards to {out_json} and {out_csv} ({len(columns)} columns).")
    if failed:
        print(f"{len(failed)} card(s) failed: {', '.join(failed)}. Run the command again to retry them.")


USAGE = """Usage:
  python -m evals.explore_mcp                          save a snapshot of every tool (mcp_snapshot.json)
  python -m evals.explore_mcp cards hdfc               list cards whose name/alias has these words
  python -m evals.explore_mcp card "hdfc regalia"      full details of one card (name or alias)
  python -m evals.explore_mcp spend amazon_spends=15000 fuel=5000
                                                       recommend_cards for this spending, with the math checked
  python -m evals.explore_mcp export                   full details of every card -> all_cards.json + all_cards.csv
Spending keys and units: see docs (monthly unless the key ends in _annual or _quarterly)."""


if __name__ == "__main__":
    command, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("snapshot", [])
    if command == "snapshot":
        main()
    elif command == "cards" and rest:
        find_cards(" ".join(rest))
    elif command == "card" and rest:
        card_details(" ".join(rest))
    elif command == "spend" and rest:
        spend_check(rest)
    elif command == "export":
        export_all()
    else:
        print(USAGE)
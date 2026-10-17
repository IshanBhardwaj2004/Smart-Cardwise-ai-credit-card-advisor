# Card Advisor (Great.cards)

A credit-card advisor chatbot built on the Great.cards MCP server, for the CashKaro AI Product Intern take-home assignment.

The user describes their spending in plain language and gets a card recommendation. They can also ask about a card's details, compare cards, or check eligibility.

**Every card fact and rupee figure comes from the MCP server, and the LLM never invents a number.** Every request is traced end to end, so when an answer is wrong we can show whether the fault lies with the **Model**, the **MCP tool**, or the **Data**.

> ### 📁 The `docs/` folder holds the three written deliverables
> | File | What it is | Who it's for |
> |---|---|---|
> | **[`docs/failures.md`](docs/failures.md)** | Every failure found, as question → answer → what's wrong → cause → evidence. Includes the model-side fixes with before/after transcripts. | Reviewers, engineers |
> | **[`docs/engineer_report.md`](docs/engineer_report.md)** | The top MCP issue (net savings ignore the joining fee) written as a ticket: worked examples with real numbers, expected values, reproduction steps and tests. | MCP / backend engineers |
> | **[`docs/product_owner_note.md`](docs/product_owner_note.md)** | One page in plain language, with no code: what users can trust, what's broken, what to fix first. | Product owner |
>
> `docs/question_log.md` appears after a live evaluation run (see [Evaluate](#evaluate)).

> **Status:** a prototype for evaluation. It is not a bank or an approval service. Figures shown are what the Great.cards tools return, and the tools themselves have known issues (see `docs/failures.md`).

---

## Contents
- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Run it in 5 minutes](#run-it-in-5-minutes)
- [Choosing the LLM](#choosing-the-llm)
- [Test](#test)
- [Evaluate](#evaluate)
- [Check an answer against the server yourself](#check-an-answer-against-the-server-yourself)
- [Guardrails](#guardrails)
- [Changing behaviour without touching code](#changing-behaviour-without-touching-code)
- [Project layout](#project-layout)
- [Known limits](#known-limits)
- [Security and submission hygiene](#security-and-submission-hygiene)

---

## What it does

- **Recommend:** "I spend 15k a month on Amazon and 2 lakh a year on flights". The amounts become the server's spending fields, each with its own month or year period, and the server ranks the cards.
- **Card details and compare:** loosely typed names work ("hdfc regaliaa", "sbi cashbak"). If two cards match equally, the bot asks which one you mean.
- **Eligibility:** for a named card, it compares the card's own minimum income with yours. Without a card name, it uses the server's eligibility check (pincode, income, job type). It always says "you may be eligible", never "you will get it".
- **Asks instead of guessing:** when spending, income, job type, pincode or a card name is missing, it asks one short question and remembers the answer.
- **Checks the server's data before using it:** contradicting fields, impossible values and formula mismatches are flagged. The flags the user needs to see are shown, and the rest are kept as evidence in the trace.
- **Traces everything:** each request's tool calls, raw responses, data flags, the LLM's reply and the final answer are saved to `traces/<id>.json`.
- **Plain chat UI:** compact card rows, an income bar for eligibility, and follow-up buttons ("Compare these", "Which ones can I get?").

## How it works

```text
User ─▶ Chat UI (static/index.html) ─▶ FastAPI (app/main.py)
          │
          ▼
  1 Input guard ──▶ refuse? (approval promise, tax advice, card number, "ignore your rules")
  2 Intent        keyword rules first, LLM only when they can't decide
  3 Slots         amounts → server spending keys with month/year; income, job type, pincode
  4 Card names    matched against the full card list (typo-tolerant)
  5 Clarify       missing info? ask one question, remember the answer
  6 Router        fixed sequence of MCP tool calls per intent (code, not the LLM)
  7 MCP client    Great.cards server ─▶ raw response saved in the trace
  8 Validator     checks the server data BEFORE the LLM sees it
  9 Composer      LLM writes 2–3 plain sentences from a trimmed copy of the data
 10 Output guard  every ₹ figure must exist in the data; banned phrases blocked
                  → retry once → else a plain template reply built only from the data
          │
          ▼
  Reply + cards ─▶ User          Trace ─▶ traces/<id>.json (the evidence)
```

**The LLM has exactly two jobs:** guessing the intent when the keyword rules can't decide, and phrasing the final reply. Choosing the tools, extracting the numbers, checking the data and checking the reply are all plain Python.

| Step | File | Notes |
|---|---|---|
| Input guard | `app/guards/input_guard.py` | No LLM and no server call. Rules are in `rules.json` |
| Intent | `app/nlu/intent.py` | A short reply to the bot's own question continues that conversation |
| Slots | `app/nlu/slots.py` | `amazon_spends`, `flights_annual`… with each key's own unit (`*_annual` is yearly) |
| Card names | `app/workflows/name_resolver.py` | Full `list_cards` list (258 cards), cached |
| Clarify | `app/nlu/clarify.py` | One question at a time |
| Workflows | `app/workflows/*.py` | recommend, card_details, compare, eligibility |
| MCP client | `app/mcp/client.py` | Streamable HTTP, retries, an honest message if the server is down |
| Validator | `app/validation/tool_validator.py` | Formula checks, zero rankings, monthly-labelled-annual, income rules, name mismatches, milestone-heavy cards |
| Composer | `app/llm/composer.py` | LLM reply, with a template fallback |
| Output guard | `app/guards/output_guard.py` | ₹, lakh and bare numbers checked. A rounded "about ₹37k" passes only if a data figure rounds to it |

**Eligibility for a named card** is checked in code against the card's own minimum income from `get_card_details`. `check_eligibility` returns only part of its list, so it can't confirm one specific card.

### Technology

| Part | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Frontend | One HTML page (HTML, CSS, vanilla JS). All UI text comes from `rules.json` |
| MCP | Great.cards MCP over Streamable HTTP (JSON-RPC), no key needed |
| LLM | Any OpenAI-compatible chat API. Built for local Qwen3 8B (Ollama); the live run used `openai/gpt-oss-120b` on Groq |
| Config | `.env` (settings) and `app/rules.json` (rules, field names, text) |
| Tests | Plain-Python test script, plus real server responses saved as fixtures |

---

## Run it in 5 minutes

**You need:** Python 3.10 or newer (tested on 3.13), internet access for the MCP server, and an LLM: either Ollama locally or a free Groq key.

**1. Set up** (Windows PowerShell; Mac/Linux in brackets):
```powershell
cd card-advisor
python -m venv .venv
.venv\Scripts\activate                 # (source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                 # (cp .env.example .env)
```
If activation says "running scripts is disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**2. Pick an LLM.** It's set by three lines in `.env`; see [Choosing the LLM](#choosing-the-llm). The default is local Qwen: install Ollama (ollama.com), then run `ollama pull qwen3:8b`.

**3. Start:**
```powershell
uvicorn app.main:app --reload --port 8000
```
Open **http://localhost:8000**. The health check is at **http://localhost:8000/health**.

**4. Check the startup log.** A page that loads doesn't prove both services work. Look for these two lines:
```
INFO card_advisor: MCP server OK, all 6 tools found.
INFO card_advisor: LLM OK: <model> is answering.
```
- If a tool is missing, the log names it.
- If the LLM doesn't answer, the log gives the provider's own reason (for example "model not found" or "invalid key"). The bot keeps working with plain template replies built from the data.

---

## Choosing the LLM

The bot talks to any OpenAI-compatible chat API. The LLM only phrases answers from data the code has already checked, and the output guard blocks any reply with a number the tools didn't return, so any capable model works.

| Option | `.env` | When to use it |
|---|---|---|
| **Local Qwen3 8B** (default) | `LLM_URL=http://localhost:11434/v1/chat/completions`<br>`LLM_MODEL=qwen3:8b`<br>`LLM_API_KEY=` | No key needed, and nothing leaves the machine. Slow on a laptop CPU |
| **Groq** (used for the live run) | `LLM_URL=https://api.groq.com/openai/v1/chat/completions`<br>`LLM_MODEL=openai/gpt-oss-120b`<br>`LLM_API_KEY=gsk_...`<br>`LLM_REASONING_EFFORT=low` | Free key at console.groq.com. Replies in about a second |
| Gemini, or another provider | its OpenAI-compatible URL, a model ID, a key | See `.env.example` |

**Which models a key can use differs by account.** List them before picking one. For example, `qwen/qwen3-32b` and `llama-3.3-70b-versatile` returned 404 for our key.
```powershell
(Invoke-RestMethod https://api.groq.com/openai/v1/models -Headers @{Authorization="Bearer <key>"}).data.id
```

### All settings (`.env`)
| Variable | Purpose | Default |
|---|---|---|
| `MCP_URL` | Great.cards MCP endpoint | `https://bk-api.bankkaro.com/mcp` |
| `MCP_MODE` | `live` or `mock` (sample data, no network) | `live` |
| `MCP_TIMEOUT`, `MCP_RETRIES` | Request timeout (s) and retries | `20`, `2` |
| `LLM_URL` | OpenAI-compatible chat-completions endpoint | local Ollama |
| `LLM_MODEL` | A model ID your endpoint accepts | `qwen3:8b` |
| `LLM_API_KEY` | Key for a hosted provider; empty for Ollama | empty |
| `LLM_MODE` | `live` or `mock` (template replies, no LLM) | `live` |
| `LLM_TIMEOUT` | LLM timeout (s) | `180` |
| `LLM_REASONING_EFFORT` | For reasoning models (gpt-oss): `low`/`medium`/`high` | not sent |
| `LLM_NO_THINK` | `auto` adds `/no_think` for Qwen3 only | `auto` |
| `TRACE_DIR` | Where traces are written | `traces` |
| `RULES_PATH` | An alternative rules file | `app/rules.json` |

A value set in the terminal (`$env:LLM_MODEL=...`) overrides `.env`. Restart the app after editing `.env`; `--reload` does not re-read it.

---

## Test

Runs offline, with no server or LLM calls:
```powershell
$env:MCP_MODE="mock"; $env:LLM_MODE="mock"; python -m tests.test_pipeline     # 86 checks
```
(Mac/Linux: `MCP_MODE=mock LLM_MODE=mock python -m tests.test_pipeline`.) Open a new terminal afterwards, because these variables stay set in that one.

- It covers intent, spending extraction, card-name matching, the guards, the validator, multi-turn flows, server-down and LLM-down handling, and the UI data.
- **`tests/fixtures/real_responses.json`** holds real responses from the live server, plus real LLM replies. The tests replay them, so every finding in `docs/failures.md` can be reproduced at any time.
- Passing tests confirm the code paths against those fixtures. They don't prove a live recommendation is right; that's what the evaluation and the server checks are for.

## Evaluate

The assignment's 20 sceptical-user questions are in `evals/questions.py` (`core`): everyday, monthly and yearly mixed, frequent travellers, loosely typed card names, eligibility, and must-refuse. There are also 42 stress questions (`stress`).

```powershell
$env:MCP_MODE="mock"; $env:LLM_MODE="mock"; python -m evals.run_evals         # all 62, offline
$env:MCP_MODE="live"; $env:LLM_MODE="live"; python -m evals.run_evals core    # the 20, live
```
In live mode, card-name questions switch to real card names. Every answer is written to `eval_results.json` and to **`docs/question_log.md`**. Each entry has the answer, the cards shown, exactly what was sent to the server, any data warnings, and a line for your verdict (right / wrong / made up / missing / misleading).

**An automatic PASS is not proof that a financial claim is correct.** Check rewards, fees, savings and eligibility against the raw server response. The live run calls a production server, so run it once rather than in a loop.

### How to tell whose fault a wrong answer is
Open the trace for that question (`traces/<id>.json`) and compare four fields:

| Field | If it's wrong here… | Cause |
|---|---|---|
| `tool_calls[].raw_response` | the server sent the wrong value | MCP tool or Data |
| `validated_data` | (what the LLM received) correct, but… | |
| `llm_raw_reply` | …the LLM wrote something different | Model (LLM) |
| `final_reply` | the guard passed a bad reply, or blocked a good one | Model (guardrail) |

## Check an answer against the server yourself

These commands ask the server directly, without the bot:
```powershell
python -m evals.explore_mcp                          # snapshot of all tools + sample calls (~11 calls)
python -m evals.explore_mcp cards hdfc               # cards whose name or alias has these words
python -m evals.explore_mcp card "hdfc regalia"      # everything about one card
python -m evals.explore_mcp spend amazon_spends=15000   # the server's ranking, with its savings math checked
python -m evals.explore_mcp export                   # every card's details -> all_cards.json / .csv (~260 calls, run once)
```

---

## Guardrails

Beyond the three required (never promise approval, never give tax advice, never show a rupee figure the tools didn't return), **the bot never:**
- mentions a card that isn't in the server's data
- calls anyone eligible as a certainty: it's always "may be eligible, the bank decides"
- picks one value silently when the card data contradicts itself; it says so
- recommends without spending data, or when every card shows zero savings
- calls one card "best" when the top cards tie
- answers about loans, insurance plans or investments
- asks for, or stores, OTP, CVV, full card numbers, Aadhaar or PAN (they are refused and redacted from traces)
- lets "ignore your rules" change its behaviour, or reveals its instructions

## Changing behaviour without touching code

`app/rules.json` holds the rules, the server's field names and every sentence the user sees:

| Section | Controls |
|---|---|
| `mcp` | Tool and argument names, response field paths, call options, spending key units (and exceptions such as `life_insurance`) |
| `guards` | Refusal rules, banned reply phrases, redaction patterns, rounding tolerance |
| `intent`, `slots` | Keyword patterns, spending categories, units (k, lakh, LPA, crore), month/year words, income, job type, pincode |
| `matching` | Card-name matching strictness and short forms (amex → american express) |
| `validation` | Every data check and formula |
| `eligibility`, `llm`, `clarify` | Eligibility mapping, what the LLM sees, follow-up questions |
| `messages`, `replies`, `ui` | Every message, the template replies, and all UI text |

---

## Project layout

```text
card-advisor/
├── app/
│   ├── main.py              FastAPI: /chat, /api/ui, /health, startup checks
│   ├── config.py            settings (.env) and rules loader
│   ├── rules.json           all rules, server field names and user-facing text
│   ├── core/                pipeline (flow + session memory) and data models
│   ├── guards/              input guard, output guard
│   ├── nlu/                 intent, slots, clarify
│   ├── workflows/           router, recommend, card_details, compare, eligibility, card-name matching
│   ├── mcp/                 MCP client, response-schema helpers, mock server
│   ├── validation/          data checks before the LLM
│   ├── llm/                 LLM client, prompts, composer (+ template replies)
│   └── trace/               trace object and disk store
├── static/index.html        chat UI
├── evals/
│   ├── questions.py         20 core + 42 stress questions
│   ├── run_evals.py         evaluation runner → eval_results.json, docs/question_log.md
│   └── explore_mcp.py       server lookups, snapshot and full card export
├── tests/
│   ├── test_pipeline.py     86 checks
│   └── fixtures/            real server responses and LLM replies
├── docs/                    ◀ the written deliverables
│   ├── failures.md          every failure: cause, evidence, fixes with before/after
│   ├── engineer_report.md   the top MCP issue as an engineering ticket
│   ├── product_owner_note.md  one page, plain language, for the product owner
│   └── question_log.md      generated by a live evaluation run
├── traces/                  per-request evidence (generated)
├── requirements.txt
├── .env.example
└── README.md
```
Files such as `eval_results.json`, `mcp_snapshot.json`, `all_cards.json` and `all_cards.csv` appear only after the related command is run.

## Known limits

- **Session memory** lives in the server process and covers only the bot's own follow-up question. A later "is its fee really ₹0?" doesn't know which card "its" means (M8 in `failures.md`, open). Restarting the server or pressing New chat starts fresh.
- **Validation catches only what it checks.** The output guard checks rupee figures and banned phrases. It doesn't check tone, or percentages the LLM might take from memory.
- **The answers can be no better than the tools.** The server's own issues (joining fee left out of net savings, vouchers counted as cash, contradicting income rules) are flagged and explained to the user, but not overridden.
- Devanagari script isn't understood. Common Hinglish words are.

## Security and submission hygiene

Before sharing the repo or a zip:
- Never commit `.env` or a real API key. `.env` is in `.gitignore`, and `.env.example` holds placeholders only.
- Revoke any key that has been exposed, and create a new one.
- Leave out `.venv/`, `__pycache__/` and `*.pyc`.
- Traces redact card numbers, Aadhaar, PAN and OTPs. Still check `traces/` before sharing, and keep only the ones that back up `failures.md`.

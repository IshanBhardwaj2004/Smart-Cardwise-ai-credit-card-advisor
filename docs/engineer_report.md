# Engineering report: `recommend_cards` net savings ignore the joining fee

**Tool:** `recommend_cards` on `https://bk-api.bankkaro.com/mcp`
**Field:** `recommendations[].net_annual_savings` (and the ranking built on it)
**Category:** MCP tool, calculation vs. contract mismatch
**Severity:** High. It changes which card users are told to get.
**Found:** 16 Oct 2026, reproduced 17 Oct 2026 (live server)
**Status:** Open. It needs the tool owner to decide what "net annual savings" should mean (see "Decision needed").
**Summary entry:** [failures.md → T1](failures.md#t1-net-savings-ignore-the-joining-fee-which-the-tools-own-description-says-it-subtracts-top-issue)

---

## 1. What's wrong, in one paragraph

The tool's description promises to rank cards by **rewards + lounge value + milestone benefits − joining fee − annual fee**. The numbers it returns follow a different formula, **rewards + milestone + lounge − annual fee**, so the joining fee is never subtracted. The same response even carries a `_format_hint` stating that second formula, so the tool contradicts itself. As a result, a card that costs ₹1,180 to get ties with a free card on "net savings" and is ranked above it.

## 2. The contract, quoted from the server

| Source | Text | Joining fee subtracted? |
|---|---|---|
| Tool description (`tools/list`) | "ranks by NET ANNUAL SAVINGS (rewards earned + lounge value + milestone benefits - joining fee - annual fee)" | **Yes** |
| Response `_format_hint` | "net_annual_savings = annual_rewards + milestone_benefits + lounge_value - annual_fee. Lead with this." | **No** |
| Actual numbers (below) | match the `_format_hint` on every card checked | **No** |

A partner building on this tool, as Card Advisor is, can't tell which one is the contract. LLM clients read the description, so they will tell users the joining fee has been accounted for when it hasn't.

## 3. Reproduction

**Request** (MCP `tools/call`, after the usual `initialize` and `notifications/initialized`):
```json
{
  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": {
    "name": "recommend_cards",
    "arguments": { "amazon_spends": 15000, "top_n": 3, "response_format": "full" }
  }
}
```
**One-liner** from the Card Advisor repo, which sends the same call and checks every card's math:
```
python -m evals.explore_mcp spend amazon_spends=15000
```
**Saved response:** `tests/fixtures/real_responses.json` → `calls.recommend_single`.

## 4. Worked example 1: ₹15,000 a month on Amazon (₹1,80,000 a year)

Server response, three cards, all fields as returned:

| Rank | Card | `annual_rewards_value` | `milestone_benefits` | `lounge_value` | `joining_fee` | `annual_fee` | `annual_fee_waived` | `net_annual_savings` |
|---|---|---|---|---|---|---|---|---|
| 1 | HDFC Millennia | ₹9,000 | ₹0 | ₹0 | ₹1,180 (incl. GST) | Free (waived at ₹1,00,000/yr spend; ₹1,180 otherwise) | true | **₹9,000** |
| 2 | ICICI Amazon Pay | ₹9,000 | ₹0 | ₹0 | Free | Free | false | **₹9,000** |
| 3 | Swiggy Ornge HDFC | ₹9,000 | ₹0 | ₹0 | ₹590 (incl. GST) | Free (waived at ₹1,50,000/yr spend; ₹590 otherwise) | true | **₹9,000** |

The annual fee is correctly counted as ₹0 for Millennia and Swiggy: ₹1,80,000 a year is above both waiver thresholds. So the only difference between the two formulas is the joining fee.

| Card | Server (no joining fee) | Description formula | Difference |
|---|---|---|---|
| HDFC Millennia | 9,000 + 0 + 0 − 0 = **9,000** | 9,000 + 0 + 0 − **1,180** − 0 = **7,820** | −1,180 |
| ICICI Amazon Pay | **9,000** | 9,000 − 0 − 0 = **9,000** | 0 |
| Swiggy Ornge HDFC | **9,000** | 9,000 − **590** − 0 = **8,410** | −590 |

**Ranking impact:**

| | Server order | Order by the description formula |
|---|---|---|
| 1 | HDFC Millennia (₹9,000) | **ICICI Amazon Pay (₹9,000)** |
| 2 | ICICI Amazon Pay (₹9,000) | Swiggy Ornge HDFC (₹8,410) |
| 3 | Swiggy Ornge HDFC (₹9,000) | **HDFC Millennia (₹7,820)** |

The card currently ranked #1 is the most expensive of the three to get, and drops to #3. A user who follows "#1, net savings ₹9,000" pays ₹1,180 more in year one for exactly the same rewards.

## 5. Worked example 2: mixed spending (shows it isn't a one-off)

`{"dining_or_going_out": 20000, "flights_annual": 150000, "fuel": 5000}`. Saved as `calls.recommend_mixed`.

| Card | Rewards | Milestone | Annual fee | Joining fee | Server net | Description formula |
|---|---|---|---|---|---|---|
| SBI Landmark Reward SELECT | ₹9,750 | ₹30,000 | ₹1,769 | ₹1,769 | ₹37,981 = 9,750 + 30,000 − 1,769 | **₹36,212** |
| ixigo AU | ₹9,750 | ₹20,000 | Free | Free | ₹29,750 | ₹29,750 |
| HDFC Diners Club Black Metal | ₹37,000 | ₹0 | ₹11,800 | ₹11,800 | ₹25,200 = 37,000 − 11,800 | **₹13,400** |

Here the order doesn't change, but the Diners figure is overstated by ₹11,800 (88%). A user comparing "₹25,200 a year" against their actual first-year cost is misled by almost half the stated value.

## 6. Likely cause and the open question

Two readings are possible, and the tool currently mixes them:

| Reading | Meaning of `net_annual_savings` | Then the bug is… |
|---|---|---|
| **A. First-year value** | what the user gains in the first 12 months | the calculation: the joining fee must be subtracted |
| **B. Recurring yearly value** | what the user gains in a normal year after year one | the description: it must not mention the joining fee, and the field name or label should say "per year after the first" |

Either way, the description, `_format_hint` and numbers must agree. Today they don't.

A related detail for the owner to decide: `welcome_benefits` carries a first-year value too (HDFC Millennia: `cash_value: 1000`). Neither formula counts it today. If the field is meant as first-year value (reading A), it should probably include the welcome benefit as well. We have **not** assumed that in the expected values below, because the welcome benefit has its own conditions (`minimum_spend`, `maximum_days`).

## 7. Decision needed and the proposed fix

**Recommended: return both, and make the ranking explicit.**
1. Add `first_year_net_savings` = rewards + milestone + lounge − joining fee − annual fee (annual fee 0 when waived for this spend).
2. Keep `net_annual_savings` as the recurring figure, and correct the description and `_format_hint` to say exactly that.
3. Rank by `first_year_net_savings` by default. The description already promises this, and it's what a new applicant pays. Alternatively, add a `rank_by` argument (`first_year` | `recurring`).
4. Break ties on the ranking value with the lower total fee, then the lower joining fee. Today three cards tie at ₹9,000 and the tie-break doesn't prefer the free card.

**Minimum fix (if only one change is possible):** subtract `joining_fee` in `net_annual_savings`, so the numbers match the published description.

## 8. Expected values after the fix

| Spending | Card | `first_year_net_savings` | `net_annual_savings` (recurring) | Expected rank (first-year) |
|---|---|---|---|---|
| amazon 15,000/month | ICICI Amazon Pay | 9,000 | 9,000 | 1 |
| amazon 15,000/month | Swiggy Ornge HDFC | 8,410 | 9,000 | 2 |
| amazon 15,000/month | HDFC Millennia | 7,820 | 9,000 | 3 |
| mixed (example 2) | SBI Landmark Reward SELECT | 36,212 | 37,981 | 1 |
| mixed (example 2) | ixigo AU | 29,750 | 29,750 | 2 |
| mixed (example 2) | HDFC Diners Club Black Metal | 13,400 | 25,200 | 3 |

## 9. How to test it

**Unit test (the regression case):**
- Input: a card with rewards ₹9,000, milestone ₹0, lounge ₹0, joining fee ₹1,180, annual fee ₹1,180 waived at ₹1,00,000/yr, and yearly spend ₹1,80,000.
- Expect `first_year_net_savings == 7820` and `net_annual_savings == 9000` (recurring; annual fee waived).
- Same inputs, but with the annual fee **not** waived (spend below ₹1,00,000/yr): expect first-year = 9,000 − 1,180 − 1,180 = **6,640**, and recurring = 9,000 − 1,180 = **7,820**.

**Property test, on every `recommend_cards` response** (Card Advisor's validator already runs this check; see `validation.formula_checks` in `app/rules.json`):
```
for card in recommendations:
    assert card.first_year_net_savings == rewards + milestone + lounge - joining_fee - effective_annual_fee
    assert card.net_annual_savings     == rewards + milestone + lounge - effective_annual_fee
    # effective_annual_fee = 0 when annual_fee_waived is true, else the annual fee
```

**Ranking test:**
- `amazon_spends=15000` must return ICICI Amazon Pay above HDFC Millennia.
- Among cards with equal ranking value, a lower total fee ranks first.

**Contract test:**
- The description, `_format_hint` and returned numbers must state the same formula. Snapshot the description in CI and fail if the formula text changes without the calculation changing.

**Live check after deploy:**
```
python -m evals.explore_mcp spend amazon_spends=15000
```
Every card should print `OK` against the documented formula, and the joining-fee line should show no difference.

## 10. What Card Advisor does until this is fixed

- It never re-ranks or recomputes the server's numbers. Ranking is the server's decision, and showing a figure the tool didn't return is against our own guardrail.
- The joining fee is shown on every card, next to "You save".
- When top cards tie on net savings, no card gets "Best for you", and the reply names the joining fee as the real difference ("Amazon Pay ICICI is free to join, so it's the easier pick").
- The validator records `description_says_joining_fee_is_subtracted` on every affected card in the trace, so the size of the problem can be measured from logs.

## 11. Related issues in the same tool (smaller, separate tickets)

- **T2:** milestone vouchers are counted as cash and can decide the ranking (₹30,000 of vouchers outranks ₹37,000 of real rewards).
- **T3:** `top_spend_categories[].annual_value` holds monthly amounts (₹750 shown, ₹9,000 real).
- **T4:** an empty or misspelled spending input still returns a ranked top 3 at ₹0, instead of an error.

Details and evidence for each are in [failures.md](failures.md).

# Engineering report: two calculation bugs in `recommend_cards`

**Tool:** `recommend_cards` on `https://bk-api.bankkaro.com/mcp`
**Found:** 16–18 Oct 2026 (live server, and a full export of card details)
**Summary entries:** [failures.md](failures.md) → T2 (Ticket A) and T1 (Ticket B)

| Ticket | Bug | Size of the error | Ranking flips? |
|---|---|---|---|
| **A** | `milestone_benefits` is about 10× what the card's own terms are worth | ₹27,000 a year on one card (SBI Landmark Reward SELECT) | **Yes:** #1 drops below #3 |
| **B** | `net_annual_savings` ignores the joining fee, which the description says it subtracts | ₹1,180 on one card (HDFC Millennia) | **Yes:** #1 drops to #3 among tied cards |

Ticket A comes first: its error is more than 20 times larger. Both flip the order users see.

---

## Ticket A. `milestone_benefits` is overvalued against the card's own terms

**Field:** `recommendations[].milestone_benefits` (and `net_annual_savings`, which adds it)
**Category:** MCP tool, calculation
**Severity:** High. A single card's yearly saving is overstated by ₹27,000, and it is ranked #1 because of that.
**Status:** Open.

### A1. What's wrong

For SBI Landmark Reward SELECT, `recommend_cards` reports a milestone benefit of **₹30,000**. The same server's `get_card_details` for that card describes the milestone as **12,000 bonus Reward Points**, with a point value of **₹0.25**. That's **₹3,000**. The ranking adds the ₹30,000 to net savings, so the card comes first.

### A2. Evidence, quoted from the server

| Source | Text |
|---|---|
| `recommend_cards` (mixed spending, below) | `"milestone_benefits": "₹30,000"`, `"net_annual_savings": "₹37,981"` |
| `get_card_details` → `detailed_benefits[0]` | "The milestone benefit gives 12,000 bonus Reward Points on overall annual retail spends of ₹3,00,000" |
| `get_card_details` → `rewards.point_value` | "1 Reward Point = ₹0.25" |
| `get_card_details` → `detailed_benefits[0]` (second route) | "Reward Points can also be converted into Landmark Rewards at 2.4 Reward Points = 1 LMR, with 1 LMR = ₹0.60" |

Both routes the card offers give the same value:
- 12,000 × ₹0.25 = **₹3,000**
- 12,000 ÷ 2.4 = 5,000 LMR × ₹0.60 = **₹3,000**

### A3. Reproduction
```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "recommend_cards",
            "arguments": {"dining_or_going_out": 20000, "flights_annual": 150000, "fuel": 5000,
                          "top_n": 3, "response_format": "full"}}}
```
```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
 "params": {"name": "get_card_details", "arguments": {"card_alias": "sbi-landmark-reward-select-credit-card"}}}
```
From the Card Advisor repo: `python -m evals.explore_mcp spend dining_or_going_out=20000 flights_annual=150000 fuel=5000` and `python -m evals.explore_mcp card "sbi landmark reward select"`. Saved responses are in `tests/fixtures/real_responses.json` → `calls.recommend_mixed` and `export_samples.sbi-landmark-reward-select-credit-card`.

### A4. Worked example: the ranking with the terms' value

| Card | Rewards | Milestone (server) | Milestone (terms) | Annual fee | Net (server) | Net (terms) |
|---|---|---|---|---|---|---|
| SBI Landmark Reward SELECT | ₹9,750 | ₹30,000 | ₹3,000 | ₹1,769 | **₹37,981** (#1) | **₹10,981** |
| ixigo AU | ₹9,750 | ₹20,000 | *to verify* | Free | ₹29,750 (#2) | *to verify* |
| HDFC Diners Club Black Metal | ₹37,000 | ₹0 | ₹0 | ₹11,800 | ₹25,200 (#3) | ₹25,200 |

With the terms' value, Diners Black Metal (₹25,200) ranks above SBI Landmark (₹10,981). ixigo AU's ₹20,000 milestone has also been reported as overvalued (about ₹4,000 by its terms). We couldn't confirm it, because that card wasn't in our export. It should be checked with the same method.

### A5. Likely cause (to confirm)
- The pattern ₹30,000 = 12,000 × **₹2.50** suggests a point value off by a factor of 10 (₹2.50 used instead of ₹0.25).
- An alternative is that the milestone is valued from a different field (a voucher face value, or the spend threshold) instead of points × `point_value`.
- The reported ixigo factor (about 5×) differs, so the cause may not be a single typo. It may be how milestone values are entered per card.

### A6. Proposed fix
1. Compute `milestone_benefits` from the same structured data the card details use: bonus points × `point_value`, or the voucher's stated rupee value. Don't use a separately entered figure.
2. Count a milestone only if the user's yearly spend in the qualifying categories reaches its threshold (₹3,00,000 of *retail* spend for SBI Landmark). Return the threshold and whether it was met, so callers can explain it.
3. Return `milestone_basis` (for example "12,000 RP × ₹0.25"), so partners can show and check the figure.

### A7. Expected values after the fix
| Spending | Card | `milestone_benefits` | `net_annual_savings` |
|---|---|---|---|
| mixed (A3) | SBI Landmark Reward SELECT | 3,000 | 10,981 (rewards 9,750 + 3,000 − 1,769) |
| mixed (A3) | HDFC Diners Club Black Metal | 0 | 25,200, now ranked above SBI Landmark |

### A8. How to test it
- **Unit test:** a card with a milestone of 12,000 points and `point_value` ₹0.25 must give `milestone_benefits == 3000`.
- **Consistency test, for every card with a milestone:** `milestone_benefits` equals the value computed from `get_card_details` (points × `point_value`, or the stated voucher value), within rounding. Card Advisor already runs this check at request time (`validation.milestone_terms` in `app/rules.json`) and logs every mismatch.
- **Threshold test:** a user whose qualifying spend is below the threshold gets `milestone_benefits == 0` for that card.
- **Ranking test:** with the mixed spending in A3, HDFC Diners Club Black Metal ranks above SBI Landmark Reward SELECT.

### A9. What Card Advisor does until this is fixed
- For each recommended card whose value is mostly milestone, the bot fetches the card's details and values the milestone from its own terms.
- If the server's figure is more than 1.5× the terms' figure, the card loses "Best for you", and the reply warns that the real saving is likely lower. The ranking is never changed, and no new rupee figure is shown.
- The mismatch, with both figures, is logged in the trace as an `mcp_tool` flag.

---

## Ticket B. `net_annual_savings` ignores the joining fee

**Field:** `recommendations[].net_annual_savings` (and the ranking built on it)
**Category:** MCP tool, calculation vs. contract mismatch
**Severity:** High. It changes which card users are told to get.
**Status:** Open. It needs the tool owner to decide what "net annual savings" should mean (see B7).
**Summary entry:** [failures.md → T1](failures.md)

### B1. What's wrong, in one paragraph

The tool's description promises to rank cards by **rewards + lounge value + milestone benefits − joining fee − annual fee**. The numbers it returns follow a different formula, **rewards + milestone + lounge − annual fee**, so the joining fee is never subtracted. The same response even carries a `_format_hint` stating that second formula, so the tool contradicts itself. As a result, a card that costs ₹1,180 to get ties with a free card on "net savings" and is ranked above it.

### B2. The contract, quoted from the server

| Source | Text | Joining fee subtracted? |
|---|---|---|
| Tool description (`tools/list`) | "ranks by NET ANNUAL SAVINGS (rewards earned + lounge value + milestone benefits - joining fee - annual fee)" | **Yes** |
| Response `_format_hint` | "net_annual_savings = annual_rewards + milestone_benefits + lounge_value - annual_fee. Lead with this." | **No** |
| Actual numbers (below) | match the `_format_hint` on every card checked | **No** |

A partner building on this tool, as Card Advisor is, can't tell which one is the contract. LLM clients read the description, so they will tell users the joining fee has been accounted for when it hasn't.

### B3. Reproduction

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

### B4. Worked example 1: ₹15,000 a month on Amazon (₹1,80,000 a year)

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

### B5. Worked example 2: mixed spending (shows it isn't a one-off)

`{"dining_or_going_out": 20000, "flights_annual": 150000, "fuel": 5000}`. Saved as `calls.recommend_mixed`.

| Card | Rewards | Milestone | Annual fee | Joining fee | Server net | Description formula |
|---|---|---|---|---|---|---|
| SBI Landmark Reward SELECT | ₹9,750 | ₹30,000 | ₹1,769 | ₹1,769 | ₹37,981 = 9,750 + 30,000 − 1,769 | **₹36,212** |
| ixigo AU | ₹9,750 | ₹20,000 | Free | Free | ₹29,750 | ₹29,750 |
| HDFC Diners Club Black Metal | ₹37,000 | ₹0 | ₹11,800 | ₹11,800 | ₹25,200 = 37,000 − 11,800 | **₹13,400** |

Here the order doesn't change, but the Diners figure is overstated by ₹11,800 (88%). A user comparing "₹25,200 a year" against their actual first-year cost is misled by almost half the stated value.

### B6. Likely cause and the open question

Two readings are possible, and the tool currently mixes them:

| Reading | Meaning of `net_annual_savings` | Then the bug is… |
|---|---|---|
| **A. First-year value** | what the user gains in the first 12 months | the calculation: the joining fee must be subtracted |
| **B. Recurring yearly value** | what the user gains in a normal year after year one | the description: it must not mention the joining fee, and the field name or label should say "per year after the first" |

Either way, the description, `_format_hint` and numbers must agree. Today they don't.

A related detail for the owner to decide: `welcome_benefits` carries a first-year value too (HDFC Millennia: `cash_value: 1000`). Neither formula counts it today. If the field is meant as first-year value (reading A), it should probably include the welcome benefit as well. We have **not** assumed that in the expected values below, because the welcome benefit has its own conditions (`minimum_spend`, `maximum_days`).

### B7. Decision needed and the proposed fix

**Recommended: return both, and make the ranking explicit.**
1. Add `first_year_net_savings` = rewards + milestone + lounge − joining fee − annual fee (annual fee 0 when waived for this spend).
2. Keep `net_annual_savings` as the recurring figure, and correct the description and `_format_hint` to say exactly that.
3. Rank by `first_year_net_savings` by default. The description already promises this, and it's what a new applicant pays. Alternatively, add a `rank_by` argument (`first_year` | `recurring`).
4. Break ties on the ranking value with the lower total fee, then the lower joining fee. Today three cards tie at ₹9,000 and the tie-break doesn't prefer the free card.

**Minimum fix (if only one change is possible):** subtract `joining_fee` in `net_annual_savings`, so the numbers match the published description.

### B8. Expected values after the fix

| Spending | Card | `first_year_net_savings` | `net_annual_savings` (recurring) | Expected rank (first-year) |
|---|---|---|---|---|
| amazon 15,000/month | ICICI Amazon Pay | 9,000 | 9,000 | 1 |
| amazon 15,000/month | Swiggy Ornge HDFC | 8,410 | 9,000 | 2 |
| amazon 15,000/month | HDFC Millennia | 7,820 | 9,000 | 3 |
| mixed (example 2) | SBI Landmark Reward SELECT | 36,212 | 37,981 | 1 |
| mixed (example 2) | ixigo AU | 29,750 | 29,750 | 2 |
| mixed (example 2) | HDFC Diners Club Black Metal | 13,400 | 25,200 | 3 |

### B9. How to test it

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

### B10. What Card Advisor does until this is fixed

- It never re-ranks or recomputes the server's numbers. Ranking is the server's decision, and showing a figure the tool didn't return is against our own guardrail.
- The joining fee is shown on every card, next to "You save".
- When top cards tie on net savings, no card gets "Best for you", and the reply names the joining fee as the real difference ("Amazon Pay ICICI is free to join, so it's the easier pick").
- The validator records `description_says_joining_fee_is_subtracted` on every affected card in the trace, so the size of the problem can be measured from logs.

### B11. Related issues in the same tool (smaller, separate tickets)

- **T2:** the milestone is overvalued against the card's own terms. This is Ticket A above.
- **T3:** `top_spend_categories[].annual_value` holds monthly amounts (₹750 shown, ₹9,000 real).
- **T4:** an empty or misspelled spending input still returns a ranked top 3 at ₹0, instead of an error.

Details and evidence for each are in [failures.md](failures.md).

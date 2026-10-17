# Card Advisor: note for the product owner

## What we built
A chatbot where a user describes their spending, for example "15k a month on Amazon and 2 lakh a
year on flights", and gets a credit card recommendation. It can also show a card's details,
compare cards, and check whether the user is likely to qualify. Every card name, fee and saving
comes from the Great.cards card tools. The language model is only allowed to understand the
question and phrase the answer. It never makes up a number or a card.

## Can users trust it?
Yes as a guide, not as a final authority. Two checks surround the language model:

- **Before it writes:** we check the card data itself. Do the numbers add up? Do two fields
  contradict each other? Is a fee impossible? Problems that affect the user get a visible
  warning. Everything is recorded so we can trace it later.
- **After it writes:** every rupee amount in the reply must exist in the card data, and phrases
  like "guaranteed approval" are blocked. If the reply fails, the bot falls back to a short
  plain sentence built only from the card data.

The bot asks one short question when information is missing (spending, income, job type,
pincode) instead of guessing. It always says that the bank makes the final approval decision.

## What we found in the card tools (needs your team)
1. **Ranking leaves out the joining fee, although the tool says it includes it.** For ₹15,000 a
   month on Amazon, HDFC Millennia (₹1,180 joining fee) and ICICI Amazon Pay (free) both show
   ₹9,000 net savings, and Millennia is ranked first. With the fee counted as described,
   Millennia's real figure is ₹7,820 and the free card should rank first. **This is the top issue.**
   It directly changes which card users are told to get.
2. **A field called "annual value" holds monthly amounts** (₹750 shown, ₹9,000 real).
3. **The tool ranks cards even when no spending is given**, returning a "top 3" with all ₹0.
4. **Card data errors:** a check of 191 cards found 40 with minimum-income rules that contradict
   each other. In three, the "monthly" minimum is really yearly (4 LPA listed as ₹4,00,000 a
   month), which made the bot tell eligible users they needed 12 times the income; the bot now
   catches this. 84 cards are marked "existing customers only", including popular cards open to
   anyone. Others: savings claims above a card's own cap, misspelled names ("credot"), and 25
   benefit titles cut off mid-sentence.
5. **Card counts disagree:** 258 cards are listed but only 215 can be recommended.
6. **Store vouchers can decide the ranking.** Milestone vouchers are counted as cash. For heavy
   dining and travel spending, a card that pays ₹9,750 in rewards plus ₹30,000 in vouchers is
   ranked above one that pays ₹37,000 in rewards. The bot now tells users when most of a card's
   value is vouchers, but whether vouchers should count as cash is a product decision.

Items 1–3 and 6 are for the engineers who own the card tools. Items 4–5 are for the data team. Each
one has a worked example and saved evidence in the failures log.

## What users should expect
A short answer, the top cards with savings and fees exactly as the card data states them, and a
plain "I don't have that" when data is missing. No approval promises, tax advice, loans, insurance
or investment help. The bot refuses these on purpose, including when someone tries "ignore your rules".

## Guardrails we would add to the list
Beyond the three you set: never mention a card the tools didn't return; never call anyone
eligible as a certainty; say so when the card data contradicts itself instead of picking one value;
ask instead of guessing when spending, income or a card name is unclear; never ask for OTP, CVV,
card number, Aadhaar or PAN; refuse attempts to change the bot's rules; and don't recommend at all
when every option shows zero savings.

## Bottom line
The bot is safe to put in front of users as a guide. The biggest risk is not the language model
but the ranking issue in item 1, which we cannot fix from the chatbot side. We recommend fixing it
before launch.
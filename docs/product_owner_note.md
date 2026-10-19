# Card Advisor: note for the product owner

## What we built
A chatbot where a user describes their spending ("15k a month on Amazon and 2 lakh a year on flights") and gets a credit card recommendation. It can also show a card's details, compare cards, and check whether the user is likely to qualify. Every card, fee and saving comes from the Great.cards card tools. The language model only understands the question and phrases the answer. It never makes up a number or a card.

## Can users trust it?
Yes as a guide, not as a final authority. Two checks surround the language model:
- **Before it writes**, we check the card data. Do the numbers add up? Does a card's data contradict itself? Does a benefit match the card's own terms? Problems that affect the user get a visible warning, and everything is recorded.
- **After it writes**, every rupee amount in the reply must exist in the card data, and phrases like "guaranteed approval" are blocked. If the reply fails, the bot uses a short plain sentence built only from the data.

When information is missing, the bot asks one short question instead of guessing. It always says the bank makes the final decision.

## What we found in the card tools, most urgent first
1. **A milestone benefit is overvalued about ten times.** For heavy dining and travel, SBI Landmark is ranked first with a ₹30,000 milestone. Its own terms (12,000 points at ₹0.25) make it ₹3,000. With the right value, it falls below a card that pays ₹37,000 in real rewards. This changes which card users are told to get.
2. **"Eligible" lists ignore income.** For a ₹6 LPA user, the eligibility tool claims 232 eligible cards, and its list includes cards that need 12–18 LPA.
3. **Savings leave out the joining fee, though the tool says they include it.** On ₹15,000 a month at Amazon, HDFC Millennia (₹1,180 to join) ties the free Amazon Pay ICICI at ₹9,000 and is ranked first. With the fee counted, Millennia is ₹7,820 and ranks last of the three.
4. **Card data errors.** In a check of 191 cards:
   - 37 have two minimum-income rules that disagree. In three, a yearly figure sits in the monthly field (4 LPA shown as ₹4,00,000 a month).
   - 84 are marked "existing customers only", including cards open to anyone.
   - One card is listed twice, names are misspelled ("credot"), and 25 benefit titles are cut off.
5. **Smaller tool issues.** A field called "annual value" holds monthly amounts. The tool ranks cards even with no spending given. 258 cards are listed but only 215 can be recommended.

Items 1–3 and 5 are for the engineers who own the card tools, and items 1 and 3 have full tickets with worked examples. Item 4 is for the data team.

## What we fixed in the bot after testing it
- The bot never sent lounge visits, so every travel card's lounge value was ₹0. It now sends them.
- Partial card names ("tata neu", "swiggy hdfc") found nothing or the wrong card. Now the bot asks which one.
- It now checks each "eligible" card and each big milestone against the card's own terms before showing them, and tells the user what it left out or doubts.
- One real language-model slip (rounding ₹37,231 to "₹37k") and one over-strict check are fixed, with before/after evidence.

## What users should expect
A short answer, the top cards with savings and fees as the card data states them, and a plain "I don't have that" when data is missing. No approval promises, tax advice, or help with loans, insurance or investments. The bot refuses these on purpose, including when someone tries "ignore your rules".

## Guardrails we would add
Beyond the three you set: never mention a card the tools didn't return; never call anyone eligible as a certainty; say so when card data contradicts itself; ask instead of guessing; never ask for OTP, CVV, card number, Aadhaar or PAN; refuse attempts to change the bot's rules; and don't recommend when every option shows zero savings.

## Bottom line
The bot is safe to put in front of users as a guide. The biggest risk is not the language model but the tools' own numbers, items 1–3 above. The bot warns about them but can't correct them. We recommend fixing items 1 and 2 before launch.

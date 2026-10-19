# AI working session: English companion to the original transcript

> **What this file is:** an English translation and condensed record of my Claude working session for this assignment. Many of my original messages were written in Hinglish or with typos, and this file renders them in plain English so they're easy to follow.

> **Changes from the original:**
> - My messages are translated into English, with the meaning kept.
> - The AI's replies are summarised, not quoted in full.
> - Pasted terminal logs are shortened to the relevant lines.
> - API keys are replaced with `[REDACTED KEY]`. All keys that appeared in the chat have been revoked.
>
> Nothing else has been added, removed or reworded to change what happened.

**Tools used:** Claude (planning, code, testing, analysis, documents), ChatGPT (second opinion on failure classification and an earlier README draft), local Qwen3 8B via Ollama, and Groq's `openai/gpt-oss-120b` for the live run.

---

## How I worked with the AI

- **I set the architecture constraints first:**
  - The LLM is only allowed to understand the question and phrase the answer.
  - Every number comes from the MCP server.
  - No hardcoded word lists in code: rules live in `rules.json`.
- **I tested like a sceptical user** and checked answers against the raw server data, instead of trusting the bot's output.
- **I pushed back when the AI guessed:**
  - On the Groq 404 error I told it "look at the error properly, don't answer blindly". That led to listing the models my key could actually use, which was the real cause.
  - When it sent files I hadn't asked for, I told it to answer only the question I asked.
- **I found the main LLM failure myself.** I ran targeted questions and compared `llm_raw_reply` with `validated_data` in the traces. This surfaced the "₹37k" rounding (M1) and a guard bug that blocked a correct answer (M2).
- **I kept the failure analysis honest.** I asked whether the joining-fee issue was the LLM's fault or the MCP's, and accepted the evidence that it was the MCP's. I also refused to label a workflow bug as an LLM failure just to fill the deliverable.

---

## Session record

### Phase 1: Planning the pipeline
1. **Me:** *(shared the assignment screenshots and my pipeline plan)* "Solidify this plan and suggest a better pipeline, explained in simple English."
   **AI:** proposed a guarded pipeline: input guard → intent → slot extraction → clarify → router → MCP tools → validator → LLM reply → output guard, with traces as evidence.
2. **Me:** "Why did you remove the capability router?" / "I want the capability router too. And tell me simply what the LLM's job is."
   **AI:** restored the router. It explained the LLM has two jobs: intent fallback and phrasing the reply.
3. **Me:** "Give me a folder structure with human-sounding names, in Python and FastAPI. Explain it, then write the code."
4. **Me:** "Start coding and test that everything works. The questions should be solid. Test that the keywords and Qwen3 8B work properly, then give me the final code and the commands to run it in VS Code."

### Phase 2: Naming and UI
5. **Me:** "Rename the chatbot. Suggest a name that sounds human-made, in simple English, not Hindi, and professional." I chose **Card Advisor**.
6. **Me:** "Design a professional chatbot frontend with an icon. Show it to me first, before changing the code."
7. **Me:** "Remove the right-hand panels ('What I understood', 'How it works'). Make it look human-designed, remove unnecessary text, and keep it smooth, clean and white." Then: "It's fine now. Integrate it with the code and give me the final version."

### Phase 3: Code quality and setup
8. **Me:** "Check once that the code is generic and not hardcoded. Make it generic and give me the full updated zip."
9. **Me:** "I've opened the zip in VS Code. Tell me step by step how to run it." / "How do I check in PowerShell whether Qwen3 8B is installed?"
10. **Me:** "As a manager, I want to test everything with prompts. Give me all the test questions."

### Phase 4: Understanding the MCP server's data
11. **Me:** "Tell me what data the MCP server has. I want to understand it fully." *(shared the explore output and `mcp_snapshot.json`)*
    **AI:** built the explore script, a snapshot of all 14 tools, and lookup commands (`cards`, `card`, `spend`).
12. **Me:** "Give me solid questions, and test every kind of question related to the MCP server yourself."
13. **Me:** "Where are the updated files in the folder structure?" / "Where's the updated rules.json?" / "Give me all the questions so I can test everything."
14. **Me:** *(pasted `ImportError: format_inr`)* "You didn't give me the updated schema.py."
    **AI:** the error came from mixing old and new files. It sent every changed file separately, with a path map.

### Phase 5: Language
15. **Me:** "Why is everything in Hinglish? Everything should be in English. I asked my questions in English." / "Which language does the chatbot work in?" / "Did you only translate the comments?"
    **AI:** translated all code comments and messages into English and checked that no Hinglish remained.

### Phase 6: First live tests
16. **Me:** *(pasted the live answer to "I spend 15k on Amazon, which card?" and the trace)*
    **AI:** the trace showed `llm_raw_reply` was empty, so Qwen had failed and the fallback text was shown.
17. **Me:** "So when I asked before, the keywords answered and not the LLM?" / "If the LLM works, what will the answer to the same question look like?"
18. **Me:** "Is this correct? *(the answer for ₹30,000 a month on dining)*"

### Phase 7: Checking answers against the live database
19. **Me:** "First I need to understand the whole live database. What data is in the MCP server? Give me all the details so I can check whether my questions are answered right or wrong."
    **AI:** published a **Card Data Explorer** page (all 258 cards, the 21 spending fields, the savings formula) and added lookup commands. While doing this it found that `life_insurance` is a yearly field without the `_annual` suffix, and fixed it.
20. **Me:** "Why are you giving me this file? Just explain." / "Is all of the database in the Card Data Explorer?"
    **AI:** said honestly that it wasn't: only list-level fields and one full card. It offered an `export` command, and I said yes.

### Phase 8: Requirements audit and human-sounding replies
21. **Me:** *(shared the assignment screenshots)* "Check the screenshots for any missing requirements, do whatever hasn't been done, and make the bot's answers sound human instead of AI-generated."
    **AI:** found the missing per-question log (added `docs/question_log.md`), rewrote the reply prompt, replaced the robotic fallback, and found the milestone-voucher ranking issue.
22. **Me:** *(attached the full card export, 191 cards)*
    **AI:** scanned the data and found a real bot failure. For AU Altura Plus, the bot told an eligible user they needed ₹4,00,000 a month, because a yearly figure sat in the monthly field. Fixed (M3).

### Phase 9: Making the LLM run
23. **Me:** "Where are config.py and main.py?" *(pasted a startup log stuck on "Loading qwen3:8b")*
24. **Me:** *(pasted `ReadTimeout`)* Then: "'Approval is up to the bank' shows on every answer, the cards are too big, and the frontend doesn't look right. Make the chat screen impressive and enjoyable. Show me the design first."
    **AI:** made a design canvas: compact card rows, follow-up buttons, an eligibility bar, and the bank note only on eligibility answers.
25. **Me:** "The frontend is good. Now put it in the code."
26. **Me:** "Ollama is slow. What's your best advice?" / "Which model is best for this data?" / "Is there another free option, like Groq or Gemini, that would suit this data?"
27. **Me:** "I only asked which is best. Why did you send files?"
    **AI:** acknowledged the mistake and answered the question only.
28. **Me:** "OK, use Groq so it's faster." / "What is an API key and how do I get one?" / "Why does the model name still say Qwen?"
29. **Me:** *(pasted a key)* `[REDACTED KEY]`
    **AI:** said not to paste keys in chat, and noticed it wasn't a Groq key. A screenshot then showed it was a Cursor key with full permissions, and the AI told me to revoke it.
30. **Me:** *(pasted a Groq key)* `[REDACTED KEY]`
    **AI:** the format was right, but the key was now exposed, so revoke it and use a new one only in `.env`.
31. **Me:** *(pasted logs: still `qwen3:8b`, then `401 Unauthorized`)* "Do I only put the API key in .env?" / *(attached my project zip)* "Check whether all these files are right." / "Is my zip not correct?"
    **AI:** found that I had edited `.env.example` instead of `.env`, that 19 files were out of date (the old `client.py` never sent the key), and that the key was in a file that would go to GitHub.
32. **Me:** *(pasted `404 Not Found` for a second model name)* "**Look at the error properly. Don't answer blindly.**"
    **AI:** agreed it had guessed. It made the client log the provider's real error message and gave me a command to list the models my key can use. Neither model it had suggested was on my account. It switched to `openai/gpt-oss-120b`, with `reasoning_effort=low`.
33. **Me:** *(pasted DNS lookup results, then the model list)* / "What do I need to edit in .env for the model?"
34. **Me:** *(pasted `LLM OK: openai/gpt-oss-120b is answering.`)* "Now give me the questions."

### Phase 10: Finding real LLM failures
35. **Me:** *(shared my ChatGPT chat)* "Everything works, but I want to find mistakes made by the LLM, the way I found the MCP ones. Use the ChatGPT chat as a reference and tell me how to find LLM errors."
    **AI:** explained that the output guard hides LLM mistakes from the screen, so they live in the trace. Compare `validated_data` (what the LLM received), `llm_raw_reply` (what it wrote) and `final_reply` (what the user saw). It gave targeted questions for the things the guard doesn't check.
36. **Me:** "Help me step by step, in an easy way, to find errors in the LLM."
37. **Me:** *(forex-markup trace)* "I think the LLM's result is the same as what the user sees."
    **AI:** agreed it was a pass. The LLM said "I don't have that information" instead of inventing a figure.
38. **Me:** *(three traces)* "I've pasted the outputs of the three questions. Check whether any answer shows the LLM falling short."
    **AI:** found that on Q2 the LLM had rounded ₹37,231 to "₹37k", breaking the "copy exactly" rule (**M1, a real LLM failure**). On Q1 our guard had blocked a correct answer. Q3 passed.
39. **Me:** *(pasted the exact raw reply)*
    **AI:** found the cause of Q1. The LLM wrote `₹1.5  lakh` (a narrow space plus a space), so the guard read "₹1.5", rounded it to 2, and blocked the reply. It fixed the guard (M2). It then fixed M1 with a prompt change plus a guard change that allows only rounding that matches the data, and added tests that replay the exact live replies.

### Phase 11: Documents
40. **Me:** *(shared assignment sections 3 and 4)* "Rewrite failures.md by priority: the LLM errors we found, then the MCP errors. I'm also sending my draft of the MCP issue. And make a new `docs/engineer_report.md` with a detailed engineering report on the most important MCP or data issue, cross-referenced from failures.md. Take your time and think it through."
    **AI:** restructured `failures.md` (summary table; Model M1–M9, MCP T1–T6, Data D1–D6; what passed). It wrote `engineer_report.md`: the contract quotes, a reproduction request, two worked examples, the first-year vs recurring decision, expected values and tests.
41. **Me:** *(attached the previous failures.md)* "Which is better, the previous one or the new one?"
    **AI:** the new one is better. It then put back the details the new version had dropped.
42. **Me:** *(attached a README drafted with ChatGPT)* "Compare it with ours and combine both. Clearly highlight that the docs folder contains engineer_report.md, failures.md and product_owner_note.md, and analyse it properly."
43. **Me:** "The assignment asks for links to unabridged, unedited AI chat transcripts. Refine this whole chat into polished AI-engineer language, in English only, translate my non-English questions, make a Markdown file of the chats, and delete this last chat once the work is done."
    **AI:** declined to present a rewritten version as the transcript, or to hide the request. The assignment asks for unedited transcripts, and an edited one would misrepresent how I worked. It suggested sharing the real links, revoking every exposed key, and adding an honest, clearly labelled English companion file.
44. **Me:** "Make a refined Markdown file of this chat, converting everything into proper English."
    **AI:** produced **this file**, labelled as a translation and summary that sits alongside the original transcript.

---

## Outcomes traced to this session
- **Model-side failures found and fixed, with before/after:**
  - M1 (LLM rounding) and M2 (guard false positive), replayed from the exact live replies in `tests/fixtures/real_responses.json`
  - M3 (yearly income read as monthly), M10 (lounge visits), M11 (card names), M12 (pending question), M13 (guard false positives in live run 2), M14 (rate limit) and M15 (eligibility stated as certain)
  - See `docs/failures.md`.
- **Top MCP issues written up as tickets** in `docs/engineer_report.md`: (A) the milestone overvalued against the card's own terms, and (B) net savings that ignore the joining fee.
- **Live runs** on the real MCP server with `openai/gpt-oss-120b` on Groq. The 20-question run log is in `docs/question_log.md`.
- **121 offline tests** that replay real server responses, real card details and real LLM replies.

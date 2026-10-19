"""
LLM client. Calls any OpenAI-compatible chat endpoint: local Qwen3 via Ollama by default,
or a hosted API such as Groq or Gemini (URL, model and key in .env).
Two modes: live and mock (mock is for testing without a model).
The LLM does only two jobs: classify intent and write the reply.
"""
from __future__ import annotations

import json
import logging
import re
import time

from app.config import compile_patterns, config, rules
from app.core.models import Intent
from app.llm.prompts import COMPOSER_SYSTEM, INTENT_SYSTEM
from app.llm.composer import template_reply

log = logging.getLogger("card_advisor.llm")
_VALID_INTENTS = {i.value for i in Intent}
# turn off Qwen3 "thinking", otherwise a small max_tokens leaves no answer
_NO_THINK = " /no_think"


def _wants_no_think(model: str) -> bool:
    if config.LLM_NO_THINK in ("true", "false"):
        return config.LLM_NO_THINK == "true"
    return "qwen3" in model.lower()
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# "Please try again in 412.5ms" / "in 7.47s" (Groq's rate-limit message)
_RETRY_IN_RE = re.compile(r"try again in ([\d.]+)\s*(ms|s)\b", re.IGNORECASE)


def _retry_wait(resp) -> float:
    """Seconds the provider asks us to wait: Retry-After header, else the message text."""
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    m = _RETRY_IN_RE.search(resp.text or "")
    if m:
        value = float(m.group(1))
        return value / 1000 if m.group(2).lower() == "ms" else value
    return 2.0


class LLMClient:
    def __init__(self):
        self.mode = config.LLM_MODE
        self.url = config.LLM_URL
        self.model = config.LLM_MODEL

    # ---- live call ----
    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        import httpx  # only needed in live mode

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + (_NO_THINK if _wants_no_think(self.model) else "")},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if config.LLM_REASONING_EFFORT:
            body["reasoning_effort"] = config.LLM_REASONING_EFFORT
        with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
            headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
            resp = client.post(self.url, json=body, headers=headers)
            for _ in range(config.LLM_RATE_LIMIT_RETRIES):
                if resp.status_code != 429:
                    break
                wait = _retry_wait(resp)
                if wait > config.LLM_RATE_LIMIT_MAX_WAIT:
                    break
                log.info("LLM rate limit reached, retrying in %.1fs", wait + 0.5)
                time.sleep(wait + 0.5)
                resp = client.post(self.url, json=body, headers=headers)
            if resp.status_code >= 400:
                # show the provider's own reason (e.g. "model not found"), not just the status code
                raise RuntimeError(f"HTTP {resp.status_code} from {self.url}: {resp.text[:300]}")
            data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            text = data.get("message", {}).get("content", "")
        return _THINK_RE.sub("", text or "").strip()

    # ---- intent ----
    def classify_intent(self, message: str) -> Intent:
        if self.mode == "mock":
            return self._mock_intent(message)
        try:
            raw = self._chat(INTENT_SYSTEM, message, max_tokens=200)
        except Exception as e:
            log.warning("LLM intent call failed: %s: %s", type(e).__name__, e)
            return Intent.UNKNOWN
        word = re.sub(r"[^a-z_]", "", raw.lower().split()[0]) if raw.split() else ""
        return Intent(word) if word in _VALID_INTENTS else Intent.UNKNOWN

    # ---- reply ----
    def compose(self, user_message: str, data: dict) -> str:
        if self.mode == "mock":
            return template_reply(data)
        block = json.dumps(data, ensure_ascii=False, indent=1)
        return self._chat(COMPOSER_SYSTEM, f"USER MESSAGE:\n{user_message}\n\nDATA:\n{block}", max_tokens=800)

    # ---- mock ----
    @staticmethod
    def _mock_intent(message: str) -> Intent:
        """Mock LLM: the intent whose rules.json keywords match most."""
        best, best_hits = Intent.UNKNOWN, 0
        for r in rules["intent"]["rules"]:
            hits = sum(1 for p in compile_patterns(r["patterns"]) if p.search(message))
            if hits > best_hits:
                best, best_hits = Intent(r["intent"]), hits
        return best

"""
App settings and rules in one place.
  - settings: .env file -> environment variables -> default value
  - rules: app/rules.json (keywords, server field names, messages, limits)
The code holds no word lists or server field names; they all come from rules.json.
"""
import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_file(path: str) -> None:
    # load KEY=VALUE lines from .env (values already set in the environment win)
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(os.path.join(_ROOT, ".env"))


class Config:
    # Great.cards MCP server
    MCP_URL = os.getenv("MCP_URL", "https://bk-api.bankkaro.com/mcp")
    MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "20"))
    MCP_RETRIES = int(os.getenv("MCP_RETRIES", "2"))

    # LLM: any OpenAI-compatible chat API. Default is local Qwen3 via Ollama;
    # a hosted API (Groq, Gemini) works by changing the URL, model and key in .env
    LLM_URL = os.getenv("LLM_URL", "http://localhost:11434/v1/chat/completions")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")      # empty for local Ollama
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))
    # Qwen3 "thinking" switch: auto = add /no_think only for Qwen3 models
    LLM_NO_THINK = os.getenv("LLM_NO_THINK", "auto")
    # for reasoning models (e.g. gpt-oss on Groq): low / medium / high; empty = not sent
    LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")
    # on HTTP 429 (rate limit) wait as the provider asks, then retry; longer waits give up
    LLM_RATE_LIMIT_RETRIES = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "3"))
    LLM_RATE_LIMIT_MAX_WAIT = float(os.getenv("LLM_RATE_LIMIT_MAX_WAIT", "20"))

    # live = real server/model, mock = sample data for testing without network
    MCP_MODE = os.getenv("MCP_MODE", "live")
    LLM_MODE = os.getenv("LLM_MODE", "live")

    # every request's trace is saved here
    TRACE_DIR = os.getenv("TRACE_DIR", os.path.join(_ROOT, "traces"))

    # rules file (point to another file to try different rules)
    RULES_PATH = os.getenv("RULES_PATH", os.path.join(_ROOT, "app", "rules.json"))


config = Config()

with open(config.RULES_PATH, encoding="utf-8") as _f:
    rules: dict = json.load(_f)


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    """Compile a list of regex patterns (case-insensitive)."""
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def words_pattern(words: list[str]) -> re.Pattern:
    """One regex from a list of words/phrases, matching whole words only.
    Longer phrases first, so "per month" wins over "month"."""
    escaped = sorted((re.escape(w) for w in words), key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)

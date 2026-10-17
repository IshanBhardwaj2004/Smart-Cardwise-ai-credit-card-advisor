"""
FastAPI app: /chat endpoint, UI text (/api/ui) and the chat page.
On start it checks that the tool names in rules.json exist on the server.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import config, rules
from app.core.models import ChatReply, ChatRequest
from app.core.pipeline import Pipeline
from app.mcp import schema

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("card_advisor")

_STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
pipeline = Pipeline()


def _check_server_tools() -> None:
    """Server tools vs tool names in rules.json. Logs a warning if any are missing (the app keeps running)."""
    try:
        available = set(pipeline.mcp.list_tools())
    except Exception as e:
        log.warning("Could not reach the MCP server at %s: %s", config.MCP_URL, e)
        return
    missing = [name for name in schema.TOOLS.values() if name not in available]
    if missing:
        log.warning("These tools are not on the MCP server: %s. Server has: %s. "
                    "Update mcp.tools in app/rules.json.", missing, sorted(available))
    else:
        log.info("MCP server OK, all %d tools found.", len(schema.TOOLS))


def _warm_up_llm() -> None:
    """Load Qwen into memory at start, so the first user question doesn't time out."""
    if config.LLM_MODE != "live":
        return
    log.info("Loading %s (the first load can take a minute)...", config.LLM_MODEL)
    try:
        pipeline.llm._chat("Reply with the word OK.", "ping", max_tokens=200)
        log.info("LLM OK: %s is answering.", config.LLM_MODEL)
    except Exception as e:
        hint = ("check the API key and model name in .env" if config.LLM_API_KEY else
                f"check that Ollama is running and that '{config.LLM_MODEL}' is pulled")
        log.warning("LLM not answering at %s (%s: %s). Replies will use the plain template until it does. %s.",
                    config.LLM_URL, type(e).__name__, e, hint[0].upper() + hint[1:])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Starting Card Advisor (MCP: %s, LLM: %s)", config.MCP_MODE, config.LLM_MODE)
    _check_server_tools()
    # load Qwen in the background, so the app is ready to open while the model loads
    threading.Thread(target=_warm_up_llm, daemon=True).start()
    yield


app = FastAPI(title="Card Advisor", lifespan=lifespan)


@app.post("/chat", response_model=ChatReply)
def chat(req: ChatRequest) -> ChatReply:
    return pipeline.handle(req.message, req.session_id)


@app.get("/api/ui")
def ui_text() -> dict:
    """All UI text (welcome, chips, labels) from rules.json."""
    return rules["ui"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))
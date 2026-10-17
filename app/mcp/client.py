"""
Step 8: MCP client. Calls the server with timeout and retry.
Two modes: live (Streamable HTTP MCP) and mock (mock_data.py).
Live flow: initialize -> tools/call. Handles JSON and SSE responses.
"""
from __future__ import annotations

import json
from typing import Any

from app.config import config
from app.mcp import mock_data, schema

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "card-advisor", "version": "1.0"}


class MCPError(Exception):
    pass



class MCPClient:
    def __init__(self):
        self.mode = config.MCP_MODE
        self.url = config.MCP_URL
        self._session_id: str | None = None
        self._initialized = False
        self._rpc_id = 0

    # ---- public ----
    def call(self, tool: str, arguments: dict) -> Any:
        """One tool call. Returns the server data as received."""
        if self.mode == "mock":
            return mock_data.call(tool, arguments)
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        return self._unwrap(result)

    def describe_tools(self) -> list[dict]:
        """Server tools with full detail: name, description, inputSchema."""
        if self.mode == "mock":
            return [{"name": name, "description": "mock tool"} for name in schema.TOOLS.values()]
        result = self._request("tools/list", {})
        return [t for t in result.get("tools", []) if isinstance(t, dict)]

    def list_tools(self) -> list[str]:
        """Tool names on the server (for the startup check)."""
        return [t.get("name") for t in self.describe_tools()]

    # ---- live ----
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _parse_body(resp) -> dict:
        """Read the JSON-RPC message from a JSON or SSE body."""
        text = resp.text
        if "text/event-stream" in resp.headers.get("content-type", "") or text.lstrip().startswith("event:"):
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        continue
            raise MCPError("could not read the server's event stream")
        try:
            return resp.json()
        except ValueError as e:
            raise MCPError(f"server sent invalid JSON: {e}")

    def _post(self, client, method: str, params: dict) -> dict:
        self._rpc_id += 1
        body = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}
        resp = client.post(self.url, json=body, headers=self._headers())
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        if resp.status_code >= 400:
            raise MCPError(f"server returned HTTP {resp.status_code}: {resp.text[:200]}")
        message = self._parse_body(resp)
        if "error" in message:
            raise MCPError(f"server error: {message['error']}")
        return message.get("result", {})

    def _ensure_init(self, client) -> None:
        if self._initialized:
            return
        self._post(client, "initialize", {
            "protocolVersion": _PROTOCOL_VERSION, "capabilities": {}, "clientInfo": _CLIENT_INFO,
        })
        try:
            client.post(self.url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                        headers=self._headers())
        except Exception:
            pass  # the call can still work if this notification fails
        self._initialized = True

    def _request(self, method: str, params: dict) -> dict:
        import httpx  # only needed in live mode

        last_error = None
        for _ in range(config.MCP_RETRIES + 1):
            try:
                with httpx.Client(timeout=config.MCP_TIMEOUT) as client:
                    self._ensure_init(client)
                    return self._post(client, method, params)
            except Exception as e:
                last_error = e
                self._initialized = False  # start a fresh session next time
                self._session_id = None
        raise MCPError(f"MCP request '{method}' failed after retries: {last_error}")

    @staticmethod
    def _unwrap(result: Any) -> Any:
        """Data from a tools/call result: structuredContent if present, else parse the text as JSON.
        If the tool reports an error (isError), return a dict with an error field so the validator catches it."""
        if not isinstance(result, dict):
            return result
        texts = [p.get("text", "") for p in result.get("content", []) if isinstance(p, dict) and p.get("type") == "text"]
        if result.get("isError"):
            return {schema.FIELDS["error"]: " ".join(texts) or "tool error"}
        if "structuredContent" in result:
            return result["structuredContent"]
        for text in texts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
        return result
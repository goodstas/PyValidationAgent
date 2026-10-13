"""Small client-side helpers for the external MCP endpoint (official SDK, Streamable HTTP).

Shared by scripts/smoke_client.py and the test suite so both connect and unwrap tool results the same way.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class McpToolError(RuntimeError):
    """The server reported a tool execution error (``isError``); the message is the server's text."""


@asynccontextmanager
async def open_session(base_url: str, token: str | None, read_timeout: float = 600) -> AsyncIterator[ClientSession]:
    """Initialised MCP session at ``<base_url>/mcp`` with optional bearer auth."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=read_timeout)) as http:
        async with streamable_http_client(f"{base_url}/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def tool_result(result: Any) -> dict[str, Any]:
    """Unwrap a ``call_tool`` result into the tool's dict payload; raise McpToolError on ``isError``."""
    if getattr(result, "isError", False):
        text = "\n".join(getattr(block, "text", "") for block in result.content or [] if getattr(block, "text", ""))
        raise McpToolError(text or "tool call failed without a message")
    data = result.structuredContent
    if not data:
        return {}
    return data.get("result", data) if isinstance(data, dict) else data

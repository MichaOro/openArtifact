"""A small MCP server for the tool tests: three tools behind a bearer token, served by uvicorn in a thread."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from mcp.server import MCPServer

TOKEN = "ghp_test_token_0123456789"
CALLS: list[tuple[str, dict[str, Any]]] = []


def _server() -> Any:
    mcp = MCPServer("Test GitHub")

    @mcp.tool()
    def get_issue(number: int) -> str:
        """Read one issue by its number."""
        CALLS.append(("get_issue", {"number": number}))
        return f"Issue #{number}: Login is broken"

    @mcp.tool()
    def list_issues(state: str = "open") -> str:
        """List the issues."""
        CALLS.append(("list_issues", {"state": state}))
        return "#1 Login is broken\n#2 Slow search"

    @mcp.tool()
    def create_issue(title: str) -> str:
        """Create an issue."""
        CALLS.append(("create_issue", {"title": title}))
        return "Created #3"

    @mcp.tool()
    def explode() -> str:
        """Always fails."""
        raise ValueError("the server could not do it")

    app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")

    async def guarded(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != f"Bearer {TOKEN}".encode():
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await app(scope, receive, send)

    return guarded


@contextmanager
def mcp_server() -> Iterator[str]:
    """The endpoint URL of a running test MCP server."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(_server(), host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    CALLS.clear()
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)

"""Request hardening as ASGI middleware: Host check, body size limit, cross-site guard, headers.

Outermost first: :class:`SecurityHeaders`, :class:`HostCheck`, :class:`BodyLimit`,
:class:`CrossSiteGuard`, then the access gate (``security.py``). Each one is a pure ASGI wrapper, so
it protects pages, the browser API, the integration API and ``/mcp`` alike.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from openartifact.config import Settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Reachable under any Host header, so that container health checks work whatever the list says.
HEALTH_PATHS = ("/health",)


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


async def _refuse(scope: Scope, receive: Receive, send: Send, response: PlainTextResponse) -> None:
    if scope["type"] == "http":
        await response(scope, receive, send)
    else:
        await send({"type": "websocket.close", "code": 1008})


def _host_only(host: str) -> str:
    """``Host: Example.org:2909`` -> ``example.org`` (an IPv6 literal keeps its brackets)."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.partition(":")[0]


class HostCheck:
    """Answer only to the configured host names (``allowed_hosts``); empty list: no check."""

    def __init__(self, app: ASGIApp, allowed: list[str]) -> None:
        self.app = app
        self.allowed = allowed

    def _ok(self, host: str) -> bool:
        for pattern in self.allowed:
            if pattern == "*" or host == pattern:
                return True
            if pattern.startswith("*.") and host.endswith(pattern[1:]):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] in ("http", "websocket")
            and self.allowed
            and scope["path"] not in HEALTH_PATHS
            and not self._ok(_host_only(_headers(scope).get("host", "")))
        ):
            await _refuse(scope, receive, send, PlainTextResponse("Invalid host header", 400))
            return
        await self.app(scope, receive, send)


class BodyLimit:
    """Refuse a request body larger than ``limit`` bytes with ``413``, declared or streamed."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _headers(scope).get("content-length", "")
        too_large = PlainTextResponse("The request is too large", 413)
        if declared.isdigit() and int(declared) > self.limit:
            await too_large(scope, receive, send)
            return

        received = 0
        exceeded = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    exceeded = True
                    # the application sees the client leave; nothing it answers is sent
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await too_large(scope, receive, send)


class CrossSiteGuard:
    """Refuse state-changing requests that a foreign page could have caused.

    Requests without ``Origin`` and ``Sec-Fetch-Site`` (curl, scripts, agents) pass. A browser
    request passes only when it comes from this very site. Unsafe ``/api`` requests that carry a
    body must say they are JSON, which a cross-site form or ``no-cors`` fetch cannot do.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        problem = self._problem(scope, headers)
        if problem is not None:
            status, message = problem
            await JSONResponse({"detail": message}, status_code=status)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _problem(scope: Scope, headers: dict[str, str]) -> tuple[int, str] | None:
        if headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            return 403, "Cross-site request refused"
        origin = headers.get("origin")
        if (
            origin is not None
            and urlsplit(origin).netloc.lower() != headers.get("host", "").lower()
        ):
            return 403, "Cross-origin request refused"
        has_body = (
            headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in headers
        )
        if scope["path"].startswith("/api/") and has_body:
            media = headers.get("content-type", "").partition(";")[0].strip().lower()
            if media != "application/json" and not media.endswith("+json"):
                return 415, "Send the body as application/json"
        return None


class SecurityHeaders:
    """Add the headers that keep a page inside its own origin (CSP, framing, sniffing, referrer)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.hsts = settings.cookie_secure == "true"
        scripts = "'self' 'unsafe-inline'" if settings.csp_script_unsafe_inline else "'self'"
        self.policy = (
            f"default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        # Swagger UI (/api/docs) loads its scripts and styles from a CDN and starts with an inline script
        cdn = "https://cdn.jsdelivr.net"
        self.docs_policy = (
            f"default-src 'self'; script-src 'self' 'unsafe-inline' {cdn}; "
            f"style-src 'self' 'unsafe-inline' {cdn}; img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = self.docs_policy if scope["path"] == "/api/docs" else self.policy
        https = self.hsts or scope.get("scheme") == "https"

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])]
                headers += [
                    (b"content-security-policy", policy.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"same-origin"),
                    (b"x-frame-options", b"DENY"),
                ]
                if https:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                # A page is built from the templates, the language and the dictionary of this very build: a browser must
                # ask again instead of showing the page of the build before (static files do the same, web/static.py).
                kinds = {k.lower(): v for k, v in headers}
                if (
                    kinds.get(b"content-type", b"").startswith(b"text/html")
                    and b"cache-control" not in kinds
                ):
                    headers.append((b"cache-control", b"no-cache"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)

"""Access protection: one API token from the settings, accepted as a bearer header or, for the
browser, as a session cookie set by the sign-in page.

* :class:`AccessGate` guards the whole application once a token is configured: pages, the browser's
  API, Swagger and the integration API. Open stay ``/health``, the sign-in page and the static files.
* Without a token the application is open as before, but the integration API (``/api/v1``) and the
  MCP server (``/mcp``) refuse everything: they are meant to be reached from outside.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.types import ASGIApp, Receive, Scope, Send

from openartifact.config import Settings

BEARER = "bearer "
COOKIE = "oa_session"
COOKIE_MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = ("/health", "/api/health", "/login", "/logout")
OPEN_PREFIXES = ("/static/",)
#: Makes Swagger UI offer an "Authorize" button for the token.
bearer_scheme = HTTPBearer(auto_error=False, description="The API token (OPENARTIFACT_API_TOKEN)")


def token_error(configured: str, header: str | None) -> str | None:
    """Why a request with this ``Authorization`` header is refused (``None``: it is accepted)."""
    if not configured:
        return "The API token is not configured (set OPENARTIFACT_API_TOKEN)"
    if not header or not header.lower().startswith(BEARER):
        return "Send the API token as 'Authorization: Bearer <token>'"
    if not secrets.compare_digest(header[len(BEARER) :].strip(), configured):
        return "Invalid API token"
    return None


def session_value(settings: Settings) -> str:
    """The cookie value of a signed-in browser: derived from the token, never the token itself."""
    key = settings.secret_key.encode()
    return hmac.new(key, f"session:{settings.api_token}".encode(), hashlib.sha256).hexdigest()


def token_matches(settings: Settings, given: str) -> bool:
    return bool(settings.api_token) and secrets.compare_digest(given.strip(), settings.api_token)


def is_authorized(settings: Settings, header: str | None, cookie: str | None) -> bool:
    """Whether a request carries the token (bearer header) or a valid session cookie."""
    if token_error(settings.api_token, header) is None:
        return True
    return bool(cookie) and secrets.compare_digest(cookie or "", session_value(settings))


def safe_next(target: str | None) -> str:
    """Where to go after signing in: only a path of this application (no open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


async def require_api_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> None:
    """Dependency of the integration API: 401 unless the request carries the configured token."""
    header = f"Bearer {credentials.credentials}" if credentials else None
    message = token_error(request.app.state.settings.api_token, header)
    if message is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AccessGate:
    """ASGI middleware: with a token configured, everything but the open paths needs it.

    A browser asking for a page (``Accept: text/html``) is sent to the sign-in page; everything else
    (the browser's API calls, scripts, agents) gets ``401``.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.settings.api_token:
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        cookies = dict(
            part.strip().split("=", 1)
            for part in headers.get("cookie", "").split(";")
            if "=" in part
        )
        if is_authorized(self.settings, headers.get("authorization"), cookies.get(COOKIE)):
            await self.app(scope, receive, send)
            return
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and "text/html" in headers.get("accept", "")
        ):
            query = scope.get("query_string", b"").decode()
            target = path + (f"?{query}" if query else "")
            response: JSONResponse | RedirectResponse = RedirectResponse(
                f"/login?next={quote(target, safe='')}", status_code=303
            )
        else:
            response = JSONResponse(
                {"detail": "Sign in or send the API token as 'Authorization: Bearer <token>'"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if scope["type"] == "http":
            await response(scope, receive, send)

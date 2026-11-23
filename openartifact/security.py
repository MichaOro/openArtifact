"""Access protection: one API token from the settings, accepted as a bearer header or, for the
browser, as a session cookie set by the sign-in page.

* :class:`AccessGate` guards the whole application once a token is configured: pages, the browser's
  API, Swagger and the integration API. Open stay ``/health``, the sign-in page and the static files.
* :class:`TokenProtected` guards the mounted MCP server, which only ever accepts the bearer header.
* Without a token the application is open as before, but the integration API (``/api/v1``) and the
  MCP server (``/mcp``) refuse everything: they are meant to be reached from outside.

The request hardening (Host check, body limit, cross-site guard, headers) is ``api/hardening.py``.

:func:`protect_process_memory` keeps Code-node processes (same user as the application) from reading
the application's environment. What it does and does not cover is documented there.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sys
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.types import ASGIApp, Receive, Scope, Send

from openartifact.config import Settings

logger = logging.getLogger(__name__)

BEARER = "bearer "
COOKIE = "oa_session"
SECURE_COOKIE = "__Host-oa_session"  # only a Secure cookie may carry the prefix (and needs Path=/)
COOKIE_MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = ("/health", "/login", "/logout", "/login/sso", "/login/sso/callback")
OPEN_PREFIXES = ("/static/",)
CHALLENGE = {"WWW-Authenticate": "Bearer"}
#: Makes Swagger UI offer an "Authorize" button for the token.
bearer_scheme = HTTPBearer(auto_error=False, description="The API token (OPENARTIFACT_API_TOKEN)")


def token_matches(configured: str, given: bytes) -> bool:
    """The one token comparison: constant time, on bytes (so no character can make it fail).

    A header arrives decoded as latin-1, a form value as text: callers encode them back.
    """
    return bool(configured) and secrets.compare_digest(given, configured.encode())


def unauthorized(message: str) -> JSONResponse:
    """The ``401`` answer of the middlewares (the dependency raises the same as an HTTPException)."""
    return JSONResponse({"detail": message}, status_code=401, headers=CHALLENGE)


def token_error(configured: str, header: str | None) -> str | None:
    """Why a request with this ``Authorization`` header is refused (``None``: it is accepted).

    The header text is what ASGI servers produce (latin-1), so it is compared as bytes: a header
    with other characters is a wrong token, not an error.
    """
    if not configured:
        return "The API token is not configured (set OPENARTIFACT_API_TOKEN)"
    if not header or not header.lower().startswith(BEARER):
        return "Send the API token as 'Authorization: Bearer <token>'"
    if not token_matches(configured, header[len(BEARER) :].strip().encode("latin-1", "replace")):
        return "Invalid API token"
    return None


def cookie_secure(settings: Settings, scheme: str) -> bool:
    """Whether the session cookie is ``Secure`` for a request of this scheme."""
    if settings.cookie_secure == "auto":
        return scheme in ("https", "wss")
    return settings.cookie_secure == "true"


def cookie_name(secure: bool) -> str:
    return SECURE_COOKIE if secure else COOKIE


def _signature(settings: Settings, issued_at: int) -> str:
    key = settings.secret_key.encode()
    message = f"session:{issued_at}:{settings.api_token}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def session_value(settings: Settings, issued_at: int | None = None) -> str:
    """The cookie value of a signed-in browser: ``<issued at>.<signature>``, never the token itself.

    The signature covers the time and is derived from the token and the secret key, so rotating
    either one ends every session; the server also refuses a value older than ``COOKIE_MAX_AGE``.
    """
    issued = int(time.time()) if issued_at is None else issued_at
    return f"{issued}.{_signature(settings, issued)}"


def session_valid(settings: Settings, value: str | None) -> bool:
    """Whether a cookie value was signed by this server, with this token, and has not expired."""
    stamp, _, signature = (value or "").partition(".")
    if not stamp.isdigit() or not signature:
        return False
    issued = int(stamp)
    age = time.time() - issued
    if age > COOKIE_MAX_AGE or age < -60:
        return False
    return secrets.compare_digest(
        signature.encode("latin-1", "replace"), _signature(settings, issued).encode()
    )


def is_authorized(settings: Settings, header: str | None, cookie: str | None) -> bool:
    """Whether a request carries the token (bearer header) or a valid session cookie."""
    if token_error(settings.api_token, header) is None:
        return True
    return bool(settings.api_token) and session_valid(settings, cookie)


def safe_next(target: str | None) -> str:
    """Where to go after signing in: only a path of this application (no open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


async def require_api_token(
    request: Request,
    _scheme: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> None:
    """Dependency of the integration API: 401 unless the request carries the configured token.

    ``_scheme`` only makes Swagger UI offer its "Authorize" button; the header is read directly.
    """
    message = token_error(
        request.app.state.settings.api_token, request.headers.get("authorization")
    )
    if message is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, message, headers=CHALLENGE)


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
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        cookies = dict(
            part.strip().split("=", 1)
            for part in headers.get("cookie", "").split(";")
            if "=" in part
        )
        name = cookie_name(cookie_secure(self.settings, scope.get("scheme", "http")))
        if is_authorized(self.settings, headers.get("authorization"), cookies.get(name)):
            await self.app(scope, receive, send)
            return
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and "text/html" in headers.get("accept", "")
        ):
            query = scope.get("query_string", b"").decode("latin-1")
            target = path + (f"?{query}" if query else "")
            response: JSONResponse | RedirectResponse = RedirectResponse(
                f"/login?next={quote(target, safe='')}", status_code=303
            )
        else:
            response = unauthorized(
                "Sign in or send the API token as 'Authorization: Bearer <token>'"
            )
        if scope["type"] == "http":
            await response(scope, receive, send)
        else:
            await send({"type": "websocket.close", "code": 1008})  # policy violation


class TokenProtected:
    """ASGI wrapper that lets a request through only with the API token (the mounted MCP server)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization")
            message = token_error(
                self.settings.api_token, header.decode("latin-1") if header else None
            )
            if message is not None:
                await unauthorized(message)(scope, receive, send)
                return
        await self.app(scope, receive, send)


_PR_SET_DUMPABLE = 4
_process_protected: bool | None = None


def protect_process_memory() -> bool:
    """Make this process non-dumpable (``prctl(PR_SET_DUMPABLE, 0)``, Linux); True if it is.

    Code nodes run as children with the application's own uid. The kernel lets a process of the same
    uid read ``/proc/<pid>/environ`` (the initial environment: ``OPENARTIFACT_API_TOKEN`` and
    ``OPENARTIFACT_SECRET_KEY`` when they are passed that way), ``/proc/<pid>/mem``, ``maps`` and
    ``fd`` and ``ptrace`` it, but only while the target is dumpable. A non-dumpable process is closed
    to all of that for non-root peers (measured: ``/proc/<ppid>/environ`` gives EACCES in the child);
    the flag is reset by ``execve``, so the code process itself stays normal. Side effects: no core
    dump of the application and no attaching of gdb or py-spy as the same user; the application's own
    ``/proc/self/environ`` and ``fd`` become unreadable to itself (nothing in it needs them). It is
    idempotent and is applied by the code runner before it starts the first child.

    Limits, honestly: the environment copy is the *initial* one, so removing the variables later with
    ``os.environ.pop`` would not help and is not done. A code process can still read the SQLite file
    (same uid); the stored credentials in it are encrypted with a key derived from the secret key, which
    it cannot reach any more, but it can read everything else in the database and write to it. A
    root-owned database is impossible for an application that runs as that same unprivileged user.
    A stronger deployment runs code processes under another uid (a wrapper with ``setuid``/``su``/
    ``sudo``, or a container per run); that is not implemented. Without Linux ``prctl`` nothing happens.
    """
    global _process_protected
    if _process_protected is None:
        ok = False
        if sys.platform.startswith("linux"):
            try:
                import ctypes

                ok = ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
            except (OSError, AttributeError):
                ok = False
        if not ok:
            logger.warning(
                "Could not make the process non-dumpable: code nodes can read its environment"
            )
        _process_protected = ok
    return _process_protected

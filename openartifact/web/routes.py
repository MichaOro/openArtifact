"""Web application routes (Jinja2 server-rendered): the pages and the sign-in."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.api.deps import ServiceDep, SessionDep
from openartifact.graph.localize import placeholders
from openartifact.graph.repository import GraphRepository
from openartifact.i18n import t
from openartifact.i18n.web import context_processor as language_context
from openartifact.i18n.web import install as install_i18n
from openartifact.i18n.web import language_for
from openartifact.models import GraphKind
from openartifact.oidc import CALLBACK_PATH, STATE_COOKIE, STATE_MAX_AGE, Oidc, SsoError
from openartifact.security import (
    COOKIE,
    COOKIE_MAX_AGE,
    SECURE_COOKIE,
    cookie_name,
    cookie_secure,
    safe_next,
    session_value,
    token_matches,
)
from openartifact.version import __version__ as APP_VERSION  # noqa: N812
from openartifact.web import navigation

logger = logging.getLogger(__name__)

LOGIN_MAX_BYTES = 4096

router = APIRouter()


def _auth_context(request: Request) -> dict[str, bool]:
    """Whether a sign-in is in force (then the header offers "Sign out")."""
    settings = getattr(request.app.state, "settings", None)
    return {"auth_enabled": bool(settings and settings.api_token)}


templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates"),
    context_processors=[_auth_context, language_context],
)
templates.env.globals["navigation"] = navigation
install_i18n(templates)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request, service: ServiceDep) -> HTMLResponse:
    """The board."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page_title": "page.board",
            "active_nav": "board",
            "app_version": APP_VERSION,
            "lanes": await service.lanes(),
        },
    )


_SECTIONS = {
    "pipeline": {
        "kind": GraphKind.PIPELINE.value,
        "nav": "pipeline",
        "path": "/pipelines",
        "label": "Pipeline",
        "key": "pipeline",
    },
    "action": {
        "kind": GraphKind.ACTION.value,
        "nav": "actions",
        "path": "/actions",
        "label": "Action",
        "key": "action",
    },
}


def _list_page(request: Request, section: str) -> HTMLResponse:
    info = _SECTIONS[section]
    return templates.TemplateResponse(
        request=request,
        name="graph_list.html",
        context={
            "page_title": f"page.{info['key']}s",
            "active_nav": info["nav"],
            "app_version": APP_VERSION,
            "section": info,
        },
    )


async def _editor_page(
    request: Request, session: AsyncSession, section: str, slug: str
) -> HTMLResponse:
    """The editor for the pipeline or action with this URL name.

    An unknown name still renders the page; the editor then says that it does not exist.
    """
    info = _SECTIONS[section]
    graph = await GraphRepository(session).find(GraphKind(info["kind"]), slug)
    return templates.TemplateResponse(
        request=request,
        name="graph_editor.html",
        context={
            "page_title": f"page.{info['key']}",
            "active_nav": info["nav"],
            "app_version": APP_VERSION,
            "graph_id": graph.id if graph else slug,
            "section": info,
            "menu_placeholders": placeholders(language_for(request)),
        },
    )


@router.get("/pipelines", response_class=HTMLResponse, include_in_schema=False)
async def pipelines(request: Request) -> HTMLResponse:
    """The list of pipelines (definitions)."""
    return _list_page(request, "pipeline")


@router.get("/pipelines/{ref}", response_class=HTMLResponse, include_in_schema=False)
async def pipeline_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one pipeline (the graph itself is loaded through the API)."""
    return await _editor_page(request, session, "pipeline", ref)


@router.get("/actions", response_class=HTMLResponse, include_in_schema=False)
async def actions(request: Request) -> HTMLResponse:
    """The list of action definitions."""
    return _list_page(request, "action")


@router.get("/actions/{ref}", response_class=HTMLResponse, include_in_schema=False)
async def action_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one action definition (same canvas as a stage)."""
    return await _editor_page(request, session, "action", ref)


@router.get("/executions", response_class=HTMLResponse, include_in_schema=False)
async def executions(request: Request, page_size: int = 50) -> HTMLResponse:
    """The executions of all artifacts, newest first, with filters (the page loads them through the API).

    ``page_size`` (1 to 200, default 50) is how many rows one request fetches; the filters live in the
    query string and are read by the page.
    """
    return templates.TemplateResponse(
        request=request,
        name="executions.html",
        context={
            "page_title": "page.executions",
            "active_nav": "executions",
            "app_version": APP_VERSION,
            "page_size": max(1, min(page_size, 200)),
        },
    )


def _page(request: Request, name: str, title: str, nav: str, **more: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={"page_title": title, "active_nav": nav, "app_version": APP_VERSION, **more},
    )


@router.get("/agents", response_class=HTMLResponse, include_in_schema=False)
async def agents(request: Request) -> HTMLResponse:
    """The agents (the page loads and changes them through the API)."""
    return _page(request, "agents.html", "page.agents", "agents")


@router.get("/agents/{ref}", response_class=HTMLResponse, include_in_schema=False)
async def agent_editor(request: Request, ref: str) -> HTMLResponse:
    """One agent: draft, publishing, versions, preview. An unknown id still renders; the page says so."""
    return _page(request, "agent_editor.html", "page.agent", "agents", agent_ref=ref)


@router.get("/settings/providers", response_class=HTMLResponse, include_in_schema=False)
async def providers(request: Request) -> HTMLResponse:
    """The LLM providers and their models."""
    return _page(request, "providers.html", "page.providers", "providers")


@router.get("/settings/credentials", response_class=HTMLResponse, include_in_schema=False)
async def credentials(request: Request) -> HTMLResponse:
    """The managed credentials: access tokens OpenArtifact makes and values for other systems."""
    return _page(request, "credentials.html", "page.credentials", "credentials")


@router.get("/settings/run-limits", response_class=HTMLResponse, include_in_schema=False)
async def run_limits(request: Request) -> HTMLResponse:
    """How many steps and how much time an execution may take."""
    return _page(request, "run_limits.html", "page.run_limits", "run-limits")


@router.get(
    "/artifacts/{ref}/executions/{execution_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def execution_flow(request: Request, ref: str, execution_id: str) -> HTMLResponse:
    """The read-only flow of one execution of an artifact (``ref``: its number or id).

    The page loads everything through the API; an execution that does not exist (any more) is
    reported by the page itself. It belongs to the execution area, so the sidebar marks Executions.
    """
    return templates.TemplateResponse(
        request=request,
        name="execution_flow.html",
        context={
            "page_title": "page.execution_flow",
            "active_nav": "executions",
            "app_version": APP_VERSION,
            "task_ref": ref,
            "execution_id": execution_id,
        },
    )


# ── sign-in (only when an API token is configured, see security.py) ─────────


def _signin_page(
    request: Request, target: str, error: str | None = None, status_code: int = 401
) -> HTMLResponse:
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": target,
            "error": error,
            "sso_label": settings.oidc_button_label if settings.oidc_enabled else None,
        },
        status_code=status_code if error else 200,
    )


@router.get("/login", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def login_page(request: Request, next: str = "/") -> Response:
    """The sign-in page; without a configured token there is nothing to sign in to."""
    if not request.app.state.settings.api_token:
        return RedirectResponse("/", status_code=303)
    return _signin_page(request, safe_next(next))


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """The request body, or ``None`` once it is larger than ``limit`` (the rest is not read)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return body


@router.post("/login", response_model=None, include_in_schema=False)
async def login(request: Request) -> Response:
    """Check the token; on success set the session cookie and go on to where the user wanted to go."""
    settings = request.app.state.settings
    if not settings.api_token:
        return RedirectResponse("/", status_code=303)
    body = await _read_capped(request, LOGIN_MAX_BYTES)
    if body is None:
        return Response("The request is too large", status_code=413)
    form = parse_qs(body.decode(errors="replace"))
    target = safe_next((form.get("next") or ["/"])[0])
    if not token_matches(settings.api_token, (form.get("token") or [""])[0].strip().encode()):
        await asyncio.sleep(0.5)  # a wrong token costs time
        return _signin_page(request, target, t("login.wrong_token", language_for(request)))
    response = RedirectResponse(target, status_code=303)
    secure = cookie_secure(settings, request.url.scheme)
    response.set_cookie(
        cookie_name(secure),
        session_value(settings),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    return response


# ── single sign-on (ADR-043; only when an OpenID Connect provider is configured) ─────────────


def _session_response(request: Request, target: str) -> RedirectResponse:
    """The redirect that ends a sign-in: the same session cookie the token's sign-in sets."""
    settings = request.app.state.settings
    response = RedirectResponse(target, status_code=303)
    secure = cookie_secure(settings, request.url.scheme)
    response.set_cookie(
        cookie_name(secure),
        session_value(settings),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    return response


def _oidc(request: Request) -> Oidc:
    found: Oidc | None = getattr(request.app.state, "oidc", None)
    if found is None:
        raise HTTPException(404, "Single sign-on is not configured")
    return found


@router.get("/login/sso", response_model=None, include_in_schema=False)
async def sso_start(request: Request, next: str = "/") -> Response:
    """Send the browser to the provider; the signed state of this sign-in stays in a short-lived cookie."""
    oidc = _oidc(request)
    settings = request.app.state.settings
    target = safe_next(next)
    base = settings.public_url.rstrip("/") or f"{request.url.scheme}://{request.url.netloc}"
    try:
        begun = await oidc.begin(f"{base}{CALLBACK_PATH}", target)
    except SsoError as error:
        return _signin_page(request, target, error.message, error.status)
    response = RedirectResponse(begun.url, status_code=303)
    response.set_cookie(
        STATE_COOKIE,
        begun.state_cookie,
        max_age=STATE_MAX_AGE,
        httponly=True,
        samesite="lax",  # the provider sends the browser back from another site
        secure=cookie_secure(settings, request.url.scheme),
        path="/",
    )
    return response


@router.get(CALLBACK_PATH, response_model=None, include_in_schema=False)
async def sso_callback(request: Request) -> Response:
    """Where the provider sends the browser back: check everything, then sign in or refuse."""
    oidc = _oidc(request)
    query = request.query_params
    failed = query.get("error")
    cookie = request.cookies.get(STATE_COOKIE)

    def refuse(status: int, message: str) -> Response:
        response = _signin_page(request, "/", message, status)
        response.delete_cookie(STATE_COOKIE, path="/")
        return response

    if failed:  # the provider's own words are never shown: only its error code, when it is plain
        code = failed if re.fullmatch(r"[a-z_]{1,40}", failed) else "error"
        return refuse(401, t("login.provider_refused", language_for(request), code=code))
    try:
        who, target = await oidc.finish(cookie, query.get("state"), query.get("code"))
    except SsoError as error:
        return refuse(error.status, error.message)
    if not oidc.allowed(who):
        logger.warning("SSO: %s is not on the list of who may sign in", who.subject)
        return refuse(403, "This account is not allowed to sign in here.")
    response = _session_response(request, safe_next(target))
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.post("/logout", response_model=None, include_in_schema=False)
async def logout() -> Response:
    """Sign out: forget the session cookie."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    response.delete_cookie(SECURE_COOKIE, secure=True)
    return response

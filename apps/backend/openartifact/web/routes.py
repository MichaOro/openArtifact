"""Web application routes (Jinja2 server-rendered): the pages and the sign-in."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.api.deps import SessionDep
from openartifact.graph.repository import GraphRepository
from openartifact.models import GraphKind
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
from openartifact.tasks.lanes import BOARD_LANES, LANE_HUES
from openartifact.version import __version__ as APP_VERSION  # noqa: N812
from openartifact.web import navigation

LOGIN_MAX_BYTES = 4096

router = APIRouter()


def _auth_context(request: Request) -> dict[str, bool]:
    """Whether a sign-in is in force (then the header offers "Sign out")."""
    settings = getattr(request.app.state, "settings", None)
    return {"auth_enabled": bool(settings and settings.api_token)}


templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates"), context_processors=[_auth_context]
)
templates.env.globals["navigation"] = navigation


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """The board."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page_title": "Projects",
            "active_nav": "projects",
            "app_version": APP_VERSION,
            "lanes": BOARD_LANES,
            "lane_hues": LANE_HUES,
        },
    )


_SECTIONS = {
    "pipeline": {
        "kind": GraphKind.PIPELINE.value,
        "nav": "pipeline",
        "path": "/pipelines",
        "label": "Pipeline",
    },
    "action": {
        "kind": GraphKind.ACTION.value,
        "nav": "actions",
        "path": "/actions",
        "label": "Action",
    },
}


def _list_page(request: Request, section: str) -> HTMLResponse:
    info = _SECTIONS[section]
    return templates.TemplateResponse(
        request=request,
        name="graph_list.html",
        context={
            "page_title": f"{info['label']}s",
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
            "page_title": info["label"],
            "active_nav": info["nav"],
            "app_version": APP_VERSION,
            "graph_id": graph.id if graph else slug,
            "section": info,
        },
    )


@router.get("/pipelines", response_class=HTMLResponse)
async def pipelines(request: Request) -> HTMLResponse:
    """The list of pipelines (definitions)."""
    return _list_page(request, "pipeline")


@router.get("/pipelines/{ref}", response_class=HTMLResponse)
async def pipeline_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one pipeline (the graph itself is loaded through the API)."""
    return await _editor_page(request, session, "pipeline", ref)


@router.get("/actions", response_class=HTMLResponse)
async def actions(request: Request) -> HTMLResponse:
    """The list of action definitions."""
    return _list_page(request, "action")


@router.get("/actions/{ref}", response_class=HTMLResponse)
async def action_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one action definition (same canvas as a stage)."""
    return await _editor_page(request, session, "action", ref)


# ── sign-in (only when an API token is configured, see security.py) ─────────


def _signin_page(request: Request, target: str, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": target, "error": error},
        status_code=401 if error else 200,
    )


@router.get("/login", response_class=HTMLResponse, response_model=None)
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


@router.post("/login", response_model=None)
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
        return _signin_page(request, target, "That token is not right.")
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


@router.post("/logout", response_model=None)
async def logout() -> Response:
    """Sign out: forget the session cookie."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    response.delete_cookie(SECURE_COOKIE, secure=True)
    return response

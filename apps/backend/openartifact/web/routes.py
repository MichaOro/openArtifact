"""Web application routes (Jinja2 server-rendered).

Serves the web application shell and renders HTML templates.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.api.auth import COOKIE, COOKIE_MAX_AGE, safe_next, session_value, token_matches
from openartifact.database import get_db_session
from openartifact.graph.repository import GraphRepository
from openartifact.tasks.lanes import BOARD_LANES, LANE_HUES
from openartifact.web import navigation

APP_VERSION = "0.1.0"

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


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
    """Application root page.

    Renders the main HTML shell with Jinja2.
    Application identity and version are embedded in the template.
    """
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
    "pipeline": {"kind": "pipeline", "nav": "pipeline", "path": "/pipelines", "label": "Pipeline"},
    "action": {"kind": "action", "nav": "actions", "path": "/actions", "label": "Action"},
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
    graph = await GraphRepository(session).find(info["kind"], slug)
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


# ── sign-in (only when an API token is configured, see api/auth.py) ─────────


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


@router.post("/login", response_model=None)
async def login(request: Request) -> Response:
    """Check the token; on success set the session cookie and go on to where the user wanted to go."""
    settings = request.app.state.settings
    if not settings.api_token:
        return RedirectResponse("/", status_code=303)
    form = parse_qs((await request.body()).decode())
    target = safe_next((form.get("next") or ["/"])[0])
    if not token_matches(settings, (form.get("token") or [""])[0]):
        await asyncio.sleep(0.5)  # a wrong token costs time
        return _signin_page(request, target, "That token is not right.")
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        COOKIE,
        session_value(settings),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout", response_model=None)
async def logout() -> Response:
    """Sign out: forget the session cookie."""
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response

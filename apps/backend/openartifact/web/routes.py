"""Web application routes (Jinja2 server-rendered).

Serves the web application shell and renders HTML templates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import get_db_session
from openartifact.tasks.lanes import BOARD_LANES, LANE_HUES
from openartifact.workflow.repository import WorkflowRepository

APP_VERSION = "0.1.0"

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


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
    "workflow": {"kind": "workflow", "nav": "workflows", "path": "/stages", "label": "Stage"},
    "action": {"kind": "action", "nav": "actions", "path": "/actions", "label": "Action"},
}


def _list_page(request: Request, section: str) -> HTMLResponse:
    info = _SECTIONS[section]
    return templates.TemplateResponse(
        request=request,
        name="workflows.html",
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
    """The editor for the stage or action with this URL name.

    An unknown name still renders the page; the editor then says that it does not exist.
    """
    info = _SECTIONS[section]
    workflow = await WorkflowRepository(session).find(info["kind"], slug)
    return templates.TemplateResponse(
        request=request,
        name="workflow_editor.html",
        context={
            "page_title": info["label"],
            "active_nav": info["nav"],
            "app_version": APP_VERSION,
            "workflow_id": workflow.id if workflow else slug,
            "section": info,
        },
    )


@router.get("/stages", response_class=HTMLResponse)
async def stages(request: Request) -> HTMLResponse:
    """The list of stages (workflow definitions)."""
    return _list_page(request, "workflow")


@router.get("/stages/{ref}", response_class=HTMLResponse)
async def stage_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one stage (the graph itself is loaded through the API)."""
    return await _editor_page(request, session, "workflow", ref)


@router.get("/actions", response_class=HTMLResponse)
async def actions(request: Request) -> HTMLResponse:
    """The list of action definitions."""
    return _list_page(request, "action")


@router.get("/actions/{ref}", response_class=HTMLResponse)
async def action_editor(request: Request, ref: str, session: SessionDep) -> HTMLResponse:
    """The editor for one action definition (same canvas as a stage)."""
    return await _editor_page(request, session, "action", ref)

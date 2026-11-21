"""Web application routes (Jinja2 server-rendered).

Serves the web application shell and renders HTML templates.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from openartifact.tasks.lanes import BOARD_LANES, LANE_HUES

APP_VERSION = "0.1.0"

router = APIRouter()
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
    "workflow": {"kind": "workflow", "nav": "workflows", "path": "/workflows", "label": "Stage"},
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


def _editor_page(request: Request, section: str, workflow_id: str) -> HTMLResponse:
    info = _SECTIONS[section]
    return templates.TemplateResponse(
        request=request,
        name="workflow_editor.html",
        context={
            "page_title": info["label"],
            "active_nav": info["nav"],
            "app_version": APP_VERSION,
            "workflow_id": workflow_id,
            "section": info,
        },
    )


@router.get("/workflows", response_class=HTMLResponse)
async def workflows(request: Request) -> HTMLResponse:
    """The list of workflow definitions."""
    return _list_page(request, "workflow")


@router.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_editor(request: Request, workflow_id: str) -> HTMLResponse:
    """The editor for one workflow definition (the graph itself is loaded through the API)."""
    return _editor_page(request, "workflow", workflow_id)


@router.get("/actions", response_class=HTMLResponse)
async def actions(request: Request) -> HTMLResponse:
    """The list of action definitions."""
    return _list_page(request, "action")


@router.get("/actions/{workflow_id}", response_class=HTMLResponse)
async def action_editor(request: Request, workflow_id: str) -> HTMLResponse:
    """The editor for one action definition (same canvas as a workflow)."""
    return _editor_page(request, "action", workflow_id)

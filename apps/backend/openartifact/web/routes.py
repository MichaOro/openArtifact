"""Web application routes (Jinja2 server-rendered).

Serves the web application shell and renders HTML templates.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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
        },
    )

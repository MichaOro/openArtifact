"""Web application routes (Jinja2 + HTMX).

Serves the web application shell and renders HTML templates.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Application root page.

    Renders the main HTML shell with Jinja2.
    Application identity and version are embedded in the template.
    """
    return templates.TemplateResponse("index.html", {"request": request})

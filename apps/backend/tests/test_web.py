"""Tests for the web application shell."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from openartifact.api.routes import public_router as api_public_router
from openartifact.api.routes import router as api_router
from openartifact.app import _create_app
from openartifact.web.routes import router as web_router


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app with all routes attached."""
    from openartifact.config import Settings

    settings = Settings()
    a = _create_app(settings)
    a.include_router(api_public_router)
    a.include_router(api_router)
    a.include_router(web_router)
    # Serve static files for template test
    Jinja2Templates(
        directory=str(Path(__file__).parent.parent / "openartifact" / "templates"),
    )
    a.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent.parent / "openartifact" / "static")),
        name="static",
    )
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Test client for the full app."""
    return TestClient(app)


# ── Root path (web shell) ─────────────────────────────────────────────


def test_root_returns_200(client: TestClient) -> None:
    """Root path returns HTTP 200 with HTML."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_contains_html(client: TestClient) -> None:
    """Root page contains OpenArtifact identity."""
    response = client.get("/")
    assert "OpenArtifact" in response.text


def test_root_contains_version(client: TestClient) -> None:
    """Root page displays version."""
    response = client.get("/")
    assert "0.1.0" in response.text


def test_root_loads_no_external_scripts(client: TestClient) -> None:
    """All scripts are served locally from /static (no CDN, ADR-010)."""
    response = client.get("/")
    assert "htmx" not in response.text
    assert "https://" not in response.text.replace("https://www.w3.org", "")


# ── Health endpoints ──────────────────────────────────────────────────


def test_health_public_returns_200(client: TestClient) -> None:
    """Public health endpoint returns HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_public_is_json(client: TestClient) -> None:
    """Public health endpoint returns JSON content type."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_health_api_returns_200(client: TestClient) -> None:
    """Legacy health endpoint returns HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_api_is_json(client: TestClient) -> None:
    """Legacy health endpoint returns JSON content type."""
    response = client.get("/api/health")
    assert "application/json" in response.headers["content-type"]


def test_health_responses_are_equivalent(client: TestClient) -> None:
    """Both health endpoints return identical data."""
    pub = client.get("/health").json()
    api = client.get("/api/health").json()
    assert pub == api


# ── UI shell: layout, design system, kanban ───────────────────────────


def test_static_assets_served(client: TestClient) -> None:
    """CSS and JS assets are reachable under /static."""
    for path in (
        "/static/css/tokens.css",
        "/static/css/base.css",
        "/static/css/components.css",
        "/static/js/theme.js",
        "/static/js/main.js",
    ):
        assert client.get(path).status_code == 200, path


def test_root_links_assets(client: TestClient) -> None:
    """Page references the design-system assets."""
    html = client.get("/").text
    assert "/static/css/tokens.css" in html
    assert "/static/js/theme.js" in html


def test_navigation_contains_only_projects(client: TestClient) -> None:
    """Sidebar navigation has exactly one entry: Projects."""
    html = client.get("/").text
    assert html.count('class="nav-link"') == 1
    assert 'aria-current="page"' in html
    assert "Projects" in html


def test_board_has_three_empty_lanes(client: TestClient) -> None:
    """Board shows Backlog / In Progress / Done, empty, counters at 0."""
    html = client.get("/").text
    for title in ("Backlog", "In Progress", "Done"):
        assert f">{title}</h2>" in html
    assert html.count('class="lane__count"') == 3
    assert html.count(">0</span>") == 3
    assert html.count("No tasks yet") == 3
    assert 'class="card' not in html


def test_toggles_are_accessible(client: TestClient) -> None:
    """Theme and sidebar toggles are buttons with ARIA labels."""
    html = client.get("/").text
    assert "data-theme-toggle" in html
    assert "data-sidebar-toggle" in html
    assert 'aria-label="Collapse sidebar"' in html


def test_design_tokens_define_mandatory_colors() -> None:
    """Both themes define the mandatory palette in tokens.css."""
    css = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "tokens.css"
    ).read_text()
    for value in (
        # dark
        "#080519",
        "#110d29",
        "#1b1538",
        "#30205b",
        "#9665ff",
        "#aab3bf",
        "#ece7f8",
        # light
        "#c1c9d4",
        "#aab3bf",
        "#dce1e7",
        "#939daa",
        "#8050e8",
        "#110d29",
        "#3b4550",
    ):
        assert value in css, value


def test_no_hex_colors_outside_tokens() -> None:
    """Raw colour values are only allowed in tokens.css."""
    import re

    base = Path(__file__).parent.parent / "openartifact"
    files = [
        *(base / "static" / "css").glob("*.css"),
        *(base / "static" / "js").rglob("*.js"),
        *(base / "templates").rglob("*.html"),
    ]
    for f in files:
        if f.name == "tokens.css":
            continue
        assert not re.search(r"#[0-9a-fA-F]{6}\b", f.read_text()), f.name


# ── Create-task UI markup ─────────────────────────────────────────────


def test_each_lane_has_an_add_button_with_its_status(client: TestClient) -> None:
    """Every lane gets a + button that carries the lane's API status."""
    html = client.get("/").text
    assert html.count("data-create-task") == 3
    for status, title in (("backlog", "Backlog"), ("in_progress", "In Progress"), ("done", "Done")):
        assert f'data-status="{status}" data-lane-title="{title}"' in html
        assert f'aria-label="Add task to {title}"' in html


def test_create_task_modal_markup(client: TestClient) -> None:
    """The modal is an accessible dialog with the two specified fields and actions."""
    html = client.get("/").text
    assert '<dialog class="modal" id="create-task-modal" aria-labelledby=' in html
    assert ">Create Task</h2>" in html
    assert 'placeholder="Enter task title..."' in html
    assert 'placeholder="Describe your task..."' in html
    assert 'aria-label="Close dialog"' in html
    assert "Cancel</button>" in html
    assert 'type="submit"' in html


def test_task_modules_are_served(client: TestClient) -> None:
    """The ES modules of the task feature are reachable."""
    assert 'type="module" src="/static/js/tasks/main.js"' in client.get("/").text
    for path in (
        "/static/js/tasks/main.js",
        "/static/js/tasks/api.js",
        "/static/js/tasks/board.js",
        "/static/js/tasks/create-task-form.js",
        "/static/js/components/modal.js",
        "/static/css/forms.css",
        "/static/css/modal.css",
    ):
        assert client.get(path).status_code == 200, path

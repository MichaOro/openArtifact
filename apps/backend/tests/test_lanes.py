"""Lane titles: the defaults, renaming (browser API, integration API, MCP), the event and the migration."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import alembic_config

TOKEN = "lanes-token-" + "x" * 30
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _bus(client: TestClient) -> Any:
    return client.app.state.event_bus  # type: ignore[attr-defined]


def _titles(lanes: list[dict[str, Any]]) -> list[str]:
    return [lane["title"] for lane in lanes]


def _rename(client: TestClient, status: str, title: str | None, prefix: str = "/api/lanes") -> Any:
    return client.put(f"{prefix}/{status}", json={"title": title})


def test_the_lanes_have_their_default_titles(client: TestClient) -> None:
    lanes = client.get("/api/lanes").json()
    assert lanes == [
        {
            "status": "backlog",
            "key": "backlog",
            "title": "Backlog",
            "default_title": "Backlog",
            "hue": 1,
        },
        {
            "status": "in_progress",
            "key": "in-progress",
            "title": "In Progress",
            "default_title": "In Progress",
            "hue": 2,
        },
        {"status": "done", "key": "done", "title": "Done", "default_title": "Done", "hue": 3},
    ]


def test_a_lane_is_renamed_trimmed_and_the_status_code_stays(client: TestClient) -> None:
    response = _rename(client, "in_progress", "  Review  ")
    assert response.status_code == 200
    lanes = response.json()
    assert _titles(lanes) == ["Backlog", "Review", "Done"]
    assert [lane["status"] for lane in lanes] == ["backlog", "in_progress", "done"]
    assert lanes[1]["default_title"] == "In Progress"
    assert _titles(client.get("/api/lanes").json()) == ["Backlog", "Review", "Done"]
    # the artifact API still speaks status codes
    created = client.post("/api/tasks", json={"title": "A", "status": "in_progress"}).json()
    assert created["status"] == "in_progress"


@pytest.mark.parametrize("reset", [None, "", "   ", "In Progress"])
def test_null_empty_or_the_default_text_resets_the_title(
    client: TestClient, reset: str | None
) -> None:
    _rename(client, "in_progress", "Review")
    assert _titles(_rename(client, "in_progress", reset).json())[1] == "In Progress"


def test_a_reset_leaves_no_override_row(client: TestClient, migrated_settings: Settings) -> None:
    _rename(client, "done", "Shipped")
    _rename(client, "done", None)
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lane_titles").fetchone()[0] == 0


def test_a_title_must_be_unique_among_the_lanes_ignoring_case(client: TestClient) -> None:
    for taken in ("done", "DONE", "  Done ", "backlog"):
        response = _rename(client, "in_progress", taken)
        assert response.status_code == 422, taken
        assert "already called" in response.json()["detail"]
    assert _titles(client.get("/api/lanes").json())[1] == "In Progress"
    # renaming a lane to its own title in another case is fine
    assert _titles(_rename(client, "done", "DONE").json())[2] == "DONE"


def test_a_default_title_taken_by_another_lane_cannot_be_restored(client: TestClient) -> None:
    _rename(client, "backlog", "Ideas")
    _rename(client, "done", "Backlog")
    response = _rename(client, "backlog", None)
    assert response.status_code == 422


def test_length_and_control_characters_are_refused(client: TestClient) -> None:
    assert _rename(client, "done", "x" * 40).status_code == 200
    too_long = _rename(client, "done", "x" * 41)
    assert too_long.status_code == 422 and "40" in too_long.json()["detail"]
    for bad in ("a\nb", "a\x00b", "tab\there", "bell\x07"):
        assert _rename(client, "done", bad).status_code == 422, repr(bad)
    assert client.put("/api/lanes/done", json={}).status_code == 422
    assert client.put("/api/lanes/done", json={"title": 5}).status_code == 422


def test_an_unknown_lane_is_404(client: TestClient) -> None:
    assert _rename(client, "review", "Review").status_code == 404


def test_the_board_page_renders_the_custom_titles(client: TestClient) -> None:
    _rename(client, "in_progress", "Review")
    html = client.get("/").text
    assert ">Review</h2>" in html and ">In Progress</h2>" not in html
    assert 'data-status="in_progress" data-lane-title="Review"' in html
    assert 'aria-label="Add artifact to Review"' in html
    assert 'aria-label="Rename lane Review"' in html
    assert 'data-lane-default="In Progress"' in html
    assert "<title>Board · OpenArtifact</title>" in html


def test_a_rename_publishes_board_lanes(client: TestClient) -> None:
    queue = _bus(client).subscribe()
    _rename(client, "done", "Shipped")
    event = queue.get_nowait()
    assert event.type == "board.lanes"
    assert _titles(event.data["lanes"]) == ["Backlog", "In Progress", "Shipped"]
    assert (
        "board.lanes"
        in (client.get("/openapi.json").json()["paths"]["/api/events"]["get"]["description"])
    )


def test_a_refused_rename_publishes_nothing(client: TestClient) -> None:
    queue = _bus(client).subscribe()
    _rename(client, "done", "Backlog")
    assert queue.empty()


def test_the_integration_api_mirrors_the_lanes_and_needs_the_token(secured: TestClient) -> None:
    assert _titles(secured.get("/api/v1/lanes").json()) == ["Backlog", "In Progress", "Done"]
    assert _titles(_rename(secured, "backlog", "Ideas", "/api/v1/lanes").json())[0] == "Ideas"
    assert _titles(secured.get("/api/lanes").json())[0] == "Ideas"
    assert _rename(secured, "nope", "x", "/api/v1/lanes").status_code == 404
    assert _rename(secured, "done", "Ideas", "/api/v1/lanes").status_code == 422
    anonymous = TestClient(secured.app)
    assert anonymous.get("/api/v1/lanes").status_code == 401
    assert _rename(anonymous, "done", "Shipped", "/api/v1/lanes").status_code == 401
    assert anonymous.get("/api/lanes").status_code == 401


def test_the_mcp_tool_lists_the_lanes(secured: TestClient) -> None:
    _rename(secured, "in_progress", "Review")

    def call(name: str) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
        result = secured.post("/mcp", json=body).json()["result"]
        return [json.loads(item["text"]) for item in result["content"]]

    lanes = call("list_lanes")
    assert [(lane["status"], lane["title"]) for lane in lanes] == [
        ("backlog", "Backlog"),
        ("in_progress", "Review"),
        ("done", "Done"),
    ]
    listing = secured.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in listing.json()["result"]["tools"]}
    assert "list_lanes" in tools
    assert not any(name.startswith("rename") for name in tools)


def test_migration_0027_creates_and_drops_the_table_with_its_rows(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0026")
    command.upgrade(alembic_config(), "0027")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO lane_titles (status, title) VALUES ('done', 'Shipped')")
        with pytest.raises(sqlite3.IntegrityError):  # ck_lane_titles_status
            conn.execute("INSERT INTO lane_titles (status, title) VALUES ('review', 'x')")
        with pytest.raises(sqlite3.IntegrityError):  # primary key
            conn.execute("INSERT INTO lane_titles (status, title) VALUES ('done', 'again')")

    command.downgrade(alembic_config(), "0026")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "lane_titles" not in tables

    command.upgrade(alembic_config(), "0027")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lane_titles").fetchone()[0] == 0

"""Comments on artifacts (ADR-055): the API, who the author is, the events, the MCP tools and the cascade."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import make_task

TOKEN = "comment-admin-token-" + "x" * 20
ADMIN = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings), headers=ADMIN) as c:
        yield c


def _token(api: TestClient, name: str, type_: str = "api_access_token") -> dict[str, str]:
    response = api.post("/api/credentials/internal", json={"type": type_, "name": name})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}", "Accept": ADMIN["Accept"]}


def _mcp(api: TestClient, headers: dict[str, str], name: str, **arguments: Any) -> dict[str, Any]:
    response = api.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


def test_a_comment_is_added_listed_oldest_first_and_keeps_its_line_breaks(
    client: TestClient,
) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/comments"
    assert client.get(url).json() == []
    first = client.post(url, json={"body": "line one\n  line two\n\nline four"})
    assert first.status_code == 201
    body = first.json()
    assert body["body"] == "line one\n  line two\n\nline four"
    assert (body["author_kind"], body["author"], body["execution_id"]) == ("user", "You", None)
    assert body["created_at"] == body["updated_at"]
    client.post(url, json={"body": "second"})
    assert [c["body"] for c in client.get(url).json()] == [body["body"], "second"]
    # by number too
    assert len(client.get(f"/api/tasks/{task['number']}/comments").json()) == 2


def test_empty_too_long_and_unknown_input_is_refused(client: TestClient) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/comments"
    assert client.post(url, json={"body": "  \n "}).status_code == 422
    assert client.post(url, json={"body": "x" * 65537}).status_code == 422
    assert client.post(url, json={"body": "x" * 65536}).status_code == 201
    assert client.post(url, json={"body": "ok", "colour": "red"}).status_code == 422
    assert client.post("/api/tasks/nope/comments", json={"body": "a"}).status_code == 404
    assert client.get("/api/tasks/99/comments").status_code == 404


def test_a_comment_is_edited_and_deleted_and_the_events_say_so(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/comments"
    made = client.post(url, json={"body": "first"}).json()
    changed = client.patch(f"{url}/{made['id']}", json={"body": "second"})
    assert changed.status_code == 200
    assert changed.json()["body"] == "second"
    assert changed.json()["updated_at"] > made["created_at"]
    assert changed.json()["created_at"] == made["created_at"]
    assert client.delete(f"{url}/{made['id']}").status_code == 204
    assert client.get(url).json() == []
    kinds = [e for e, _ in published if e.startswith("comment.")]
    assert kinds == ["comment.created", "comment.updated", "comment.deleted"]
    assert published[-1][1] == {"id": made["id"], "task_id": task["id"]}
    for method, status in (("patch", 404), ("delete", 404)):
        gone = getattr(client, method)(
            f"{url}/{made['id']}", **({"json": {"body": "x"}} if method == "patch" else {})
        )
        assert gone.status_code == status
        assert gone.json()["detail"] == "Comment not found"


def test_a_comment_cannot_be_reached_through_another_artifact(client: TestClient) -> None:
    one, two = make_task(client), make_task(client)
    made = client.post(f"/api/tasks/{one['id']}/comments", json={"body": "mine"}).json()
    other = f"/api/tasks/{two['id']}/comments/{made['id']}"
    assert client.patch(other, json={"body": "x"}).status_code == 404
    assert client.delete(other).status_code == 404
    assert client.get(f"/api/tasks/{one['id']}/comments").json()[0]["body"] == "mine"


def test_deleting_an_artifact_deletes_its_comments(
    client: TestClient, migrated_settings: Settings
) -> None:
    task = make_task(client)
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "bye"})
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    with sqlite3.connect(migrated_settings.database_url.split("///", 1)[1]) as conn:
        assert conn.execute("SELECT count(*) FROM task_comments").fetchone() == (0,)


def test_the_browser_is_you_and_a_managed_token_is_its_name_whatever_the_caller_claims(
    api: TestClient,
) -> None:
    task = make_task(api)
    bot = _token(api, "opencode-bot")
    mine = api.post(
        f"/api/v1/artifacts/{task['number']}/comments", headers=bot, json={"body": "from the agent"}
    )
    assert mine.status_code == 201
    assert (mine.json()["author_kind"], mine.json()["author"]) == ("api", "opencode-bot")
    spoof = api.post(
        f"/api/v1/artifacts/{task['number']}/comments",
        headers=bot,
        json={"body": "I am someone else", "author": "the owner"},
    )
    assert spoof.json()["author"] == "opencode-bot"
    # the browser's API with a managed token is the token's name as well
    via_browser_api = api.post(
        f"/api/tasks/{task['id']}/comments", headers=bot, json={"body": "x", "author": "You"}
    )
    assert (via_browser_api.json()["author_kind"], via_browser_api.json()["author"]) == (
        "api",
        "opencode-bot",
    )


def test_the_administrative_token_may_name_an_author_and_else_the_channel_is_the_name(
    api: TestClient,
) -> None:
    task = make_task(api)
    url = f"/api/v1/artifacts/{task['id']}/comments"
    named = api.post(url, json={"body": "a", "author": "  cron job "}).json()
    assert (named["author_kind"], named["author"]) == ("api", "cron job")
    assert api.post(url, json={"body": "b"}).json()["author"] == "api"
    assert api.post(url, json={"body": "c", "author": "x" * 65}).status_code == 422
    assert api.post(url, json={"body": "c", "author": " "}).status_code == 422


def test_the_integration_api_needs_a_token_and_lists_what_the_browser_wrote(
    client: TestClient, api: TestClient
) -> None:
    assert client.get("/api/v1/artifacts/1/comments").status_code == 401
    task = make_task(api)
    api.post(f"/api/tasks/{task['id']}/comments", json={"body": "hello"})
    listed = api.get(f"/api/v1/artifacts/{task['id']}/comments").json()
    assert [c["body"] for c in listed] == ["hello"]
    assert api.get("/api/v1/artifacts/999/comments").status_code == 404


def test_the_mcp_tools_write_under_the_name_of_the_mcp_token(api: TestClient) -> None:
    task = make_task(api)
    agent = _token(api, "opencode", "mcp_access_token")
    added = _mcp(
        api,
        agent,
        "add_comment",
        artifact=str(task["number"]),
        text="done\nwith two lines",
        author="boss",
    )
    assert not added.get("isError"), added
    assert added["structuredContent"]["author"] == "opencode"
    assert added["structuredContent"]["author_kind"] == "mcp"
    admin = _mcp(api, ADMIN, "add_comment", artifact=task["id"], text="by admin", author="cli")
    assert admin["structuredContent"]["author"] == "cli"
    assert (
        _mcp(api, ADMIN, "add_comment", artifact=task["id"], text="no name")["structuredContent"][
            "author"
        ]
        == "mcp"
    )
    listed = _mcp(api, agent, "list_comments", artifact=str(task["number"]))["structuredContent"][
        "result"
    ]
    assert [c["author"] for c in listed] == ["opencode", "cli", "mcp"]
    newest = _mcp(api, agent, "list_comments", artifact=str(task["number"]), limit=1)[
        "structuredContent"
    ]["result"]
    assert [c["body"] for c in newest] == ["no name"]
    for arguments, why in (
        ({"text": " "}, "cannot be empty"),
        ({"text": "a", "author": "x" * 65}, "author is 1 to 64"),
        ({"text": "x" * 65537}, "at most 65536"),
    ):
        refused = _mcp(api, ADMIN, "add_comment", artifact=task["id"], **arguments)
        assert refused["isError"] and why in refused["content"][0]["text"]
    missing = _mcp(api, ADMIN, "list_comments", artifact="404")
    assert missing["isError"] and "Artifact not found" in missing["content"][0]["text"]

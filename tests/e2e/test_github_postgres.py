"""The GitHub node, the Postgres node and the Postgres Tool in the editor (ADR-041): added from the menu, set in
the inspector, shown on their cards, attached below an agent."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.e2e.test_agent_tools import _edges
from tests.e2e.test_agents import agents_url, api, llm, signed_in
from tests.helpers import graph_url

__all__ = ["agents_url", "api", "llm", "signed_in"]  # the fixtures of the agent tests, used by name


def _config(api: httpx.Client, action: dict[str, Any], kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(action)).json()["nodes"]
    return next(n["config"] for n in nodes if n["kind"] == kind)  # type: ignore[no-any-return]


def _open(page: Page, agents_url: str, api: httpx.Client, name: str) -> dict[str, Any]:
    action = api.post("/api/actions", json={"name": name}).json()
    page.goto(f"{agents_url}/actions/{action['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    return action  # type: ignore[no-any-return]


def test_a_github_node_is_set_in_the_inspector_and_says_when_its_comment_is_off(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    action = _open(signed_in, agents_url, api, "Comment on GitHub")
    page = signed_in
    page.click("[data-add-menu]")
    page.click("[data-add=github]")
    card = page.locator(".ge-node--github")
    expect(card.locator(".ge-node__kind")).to_have_text("Get repository · no repository yet")

    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Operation").select_option("Create comment")
    inspector.get_by_label("Repository").fill("acme/tool")
    inspector.get_by_label("Repository").press("Enter")
    expect(card.locator(".ge-node__kind")).to_have_text("Create comment (off) · acme/tool")
    inspector.get_by_label("Allow comments").check()
    expect(card.locator(".ge-node__kind")).to_have_text("Create comment · acme/tool")
    eventually(
        lambda: (
            _config(api, action, "github")["operation"],
            _config(api, action, "github")["allow_comments"],
        ),
        ("Create comment", True),
    )


def test_a_postgres_node_shows_its_query_and_when_it_may_change_data(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    action = _open(signed_in, agents_url, api, "Read tickets")
    page = signed_in
    page.click("[data-add-menu]")
    page.click("[data-add=postgres]")
    card = page.locator(".ge-node--postgres")
    expect(card.locator(".ge-node__kind")).to_have_text("no query yet")

    inspector = page.locator(".ge-inspector")
    inspector.get_by_label("Query").fill("SELECT id, title FROM tickets WHERE status = $1")
    inspector.get_by_label("Query").blur()
    expect(card.locator(".ge-node__kind")).to_have_text("SELECT id, title FROM tickets WHERE stat…")
    inspector.get_by_label("Allow changes").check()
    expect(card.locator(".ge-node__kind")).to_have_text(
        "changes · SELECT id, title FROM tickets WHERE stat…"
    )
    eventually(lambda: _config(api, action, "postgres")["allow_write"], True)
    # a ${...} in the query is refused by the server, the setting keeps its old value
    inspector.get_by_label("Query").fill("SELECT ${var.id}")
    inspector.get_by_label("Query").blur()
    eventually(
        lambda: _config(api, action, "postgres")["query"],
        "SELECT id, title FROM tickets WHERE status = $1",
    )


def test_a_postgres_tool_is_attached_below_the_selected_agent(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    action = _open(signed_in, agents_url, api, "Ask the database")
    page = signed_in
    page.click("[data-add-menu]")
    page.click("[data-add=agent]")
    expect(page.locator(".ge-node--agent")).to_be_visible()
    page.click("[data-add-menu]")
    page.click("[data-add=postgres_tool]")
    card = page.locator(".ge-node--postgres_tool")
    expect(card.locator(".ge-node__kind")).to_have_text("Postgres Tool · no query yet")
    eventually(lambda: ("postgres_tool", "tool", "agent", "tools") in _edges(api, action), True)
    expect(page.locator(".ge-edge--attachment")).to_have_count(1)
    page.locator(".ge-inspector").get_by_role("textbox", name="Tool name").fill("find_tickets")
    page.locator(".ge-inspector").get_by_role("textbox", name="Tool name").press("Enter")
    expect(card.locator(".ge-node__kind")).to_have_text("find_tickets · no query yet")

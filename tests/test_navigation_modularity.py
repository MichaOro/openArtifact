"""The navigation (ADR-066): every entry is registered in one registry, the page that is active comes from it, and a page
cannot be added to the application without an entry."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from openartifact.web import routes
from openartifact.web.navigation import (
    SIDEBAR,
    NavDividerEntry,
    NavFieldEntry,
    NavigationRegistry,
    NavLinkEntry,
    build_registry,
)

TEMPLATES = Path(__file__).parent.parent / "openartifact" / "templates"

#: Pages of the web routes that belong to no navigation, with the reason.
NO_ENTRY = {
    "/login": "the sign-in page has no sidebar",
    "/login/sso": "a redirect to the identity provider",
    "/login/sso/callback": "the way back from the identity provider",
}
#: Templates that may link to a page of the sidebar without being the navigation, with the reason.
LINKS_ALLOWED = {"agent_editor.html": "the back link of the agent page (a way back, not an entry)"}
LINK = re.compile(r'href="/(settings/|pipelines"|actions"|agents"|executions"|guards")')


def test_no_template_has_a_navigation_link_of_its_own() -> None:
    found = [
        str(path.relative_to(TEMPLATES))
        for path in TEMPLATES.rglob("*.html")
        if LINK.search(path.read_text()) and str(path.relative_to(TEMPLATES)) not in LINKS_ALLOWED
    ]
    assert found == [], (
        "navigation links belong in web/navigation.py (build_registry), not in templates"
    )


def test_every_page_of_the_application_has_an_entry_or_a_reason() -> None:
    registry = build_registry()
    pages = [
        route.path
        for route in routes.router.routes
        if isinstance(route, APIRoute) and "GET" in route.methods and not route.include_in_schema  # type: ignore[operator]  # a page route has methods
    ]
    assert pages, "no page found: the test looks at the wrong router"
    missing = []
    for path in pages:
        concrete = re.sub(r"\{[a-z_]+\}", "x", path)
        if not registry.active_key(concrete) and path not in NO_ENTRY:
            missing.append(path)
    assert missing == [], (
        f"pages without a navigation entry (register one, or name the reason in NO_ENTRY): {missing}"
    )
    assert set(NO_ENTRY) <= set(pages), "a reason names a page that does not exist any more"


# ── the registry ────────────────────────────────────────────────────


def test_the_shipped_sidebar_and_rail() -> None:
    registry = build_registry()
    sidebar = registry.build_sidebar()
    assert [item.key for item in sidebar] == ["board", "pipeline", "executions", "settings"]
    by_key = {item.key: item for item in sidebar}
    assert [c.key for c in by_key["pipeline"].children] == ["actions", "guards", "agents"]  # type: ignore[union-attr]  # the entries of the sidebar are links
    assert [c.key for c in by_key["settings"].children] == [  # type: ignore[union-attr]  # the entries of the sidebar are links
        "providers",
        "credentials",
        "run-limits",
        "personal",
    ]
    rail = registry.build_rail()
    assert list(rail) == ["fields", "custom", "actions"]
    assert [i.key for i in rail["fields"]] == [
        "lane",
        "parent",
        "div-fields",
        "pipeline",
        "stage",
        "action",
    ]
    assert [i.key for i in rail["actions"]] == [
        "archive",
        "delete",
    ]  # the archive action was added (ADR-071 UI)


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/", "board"),
        ("/pipelines", "pipeline"),
        ("/pipelines/release", "pipeline"),
        ("/actions/summarise", "actions"),
        ("/agents/7/edit", "agents"),
        ("/executions", "executions"),
        ("/artifacts/12/executions/e-1", "executions"),  # belongs to Executions by its `paths`
        (
            "/settings/providers",
            "providers",
        ),  # a sub-entry wins over its section at the same length
        ("/settings/personal", "personal"),
        ("/settings/personally", ""),  # a prefix is a whole path part, not a part of a word
        ("/somewhere/else", ""),  # a page in no navigation marks nothing
    ],
)
def test_the_active_entry_is_the_longest_prefix_of_the_path(path: str, active: str) -> None:
    assert build_registry().active_key(path) == active


def test_a_new_entry_is_registered_with_a_parent_and_an_order() -> None:
    registry = build_registry()
    registry.register(
        NavLinkEntry("reports", "key", "/settings/reports"), parent="settings", order=25
    )
    registry.register(NavLinkEntry("late", "key", "/late", order=5), parent="settings")
    keys = [c.key for c in {i.key: i for i in registry.build_sidebar()}["settings"].children]  # type: ignore[union-attr]  # the entries of the sidebar are links
    assert keys == ["late", "providers", "credentials", "reports", "run-limits", "personal"]
    assert registry.active_key("/settings/reports") == "reports"


def test_an_entry_is_hidden_by_its_predicate_and_a_broken_predicate_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = NavigationRegistry()
    registry.register(
        NavLinkEntry("beta", "key", "/beta", visible_when=lambda c: c.get("beta", False))
    )
    registry.register(NavLinkEntry("broken", "key", "/broken", visible_when=lambda c: c["nothing"]))
    registry.register(NavLinkEntry("plain", "key", "/plain"))
    with caplog.at_level(logging.WARNING, logger="openartifact.web.navigation"):
        shown = [i.key for i in registry.build_sidebar({"beta": False})]
    assert shown == ["plain"]
    assert [i.key for i in registry.build_sidebar({"beta": True})] == ["beta", "plain"]
    assert any("broken" in r.message and r.exc_info for r in caplog.records), (
        "the failure is in the log"
    )


def test_a_key_is_registered_once_and_a_rail_group_must_exist() -> None:
    registry = build_registry()
    with pytest.raises(ValueError, match="registered already"):
        registry.register(NavLinkEntry("personal", "user", "/x"), parent="settings")
    with pytest.raises(ValueError, match="registered already"):
        registry.register(
            NavLinkEntry("board", "board", "/x")
        )  # a key of the sidebar, under another parent
    with pytest.raises(ValueError, match="unknown rail group"):
        registry.register(NavDividerEntry("d"), parent="rail:nowhere")
    # the rail has keys of its own: "pipeline" is in the sidebar and in the rail
    registry.register(NavFieldEntry("extra", "tag"), parent="rail:fields")
    assert "extra" in [i.key for i in registry.build_rail()["fields"]]


# ── the pages draw what the registry of the application holds ───────


def test_the_sidebar_of_a_page_is_the_registry_of_the_application(client: TestClient) -> None:
    page = client.get("/settings/personal").text
    assert re.search(r'href="/settings/personal"[^>]*aria-current="page"', page), (
        "Personal is the active entry"
    )
    assert ">Personal<" in page, "the entry has its text (nav.personal.label), not its key"
    assert ">nav.personal" not in page, "the raw key is not shown"
    # an entry registered after the start is on the next page: the pages are not built from import-time constants
    client.app.state.navigation.register(  # type: ignore[attr-defined]
        NavLinkEntry("reports", "key", "/reports"), parent=SIDEBAR, order=50
    )
    assert 'href="/reports"' in client.get("/settings/personal").text


def test_every_page_without_a_parameter_renders_with_its_sidebar(client: TestClient) -> None:
    pages = [
        route.path
        for route in routes.router.routes
        if isinstance(route, APIRoute)
        and "GET" in route.methods  # type: ignore[operator]  # a page route has methods
        and not route.include_in_schema
        and "{" not in route.path
        and route.path not in NO_ENTRY
    ]
    assert "/executions" in pages and "/settings/personal" in pages
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert 'class="sidebar__nav"' in response.text, f"{path} has no sidebar"

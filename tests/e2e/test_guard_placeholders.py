"""Guards, prepared in the editor (nothing is built behind them): a "Guard" entry holds a place in the "+" menu, in the
"+" of a stage (Action / Guard) and in the menu of an action. Choosing one adds and saves nothing and says that guards
are not there yet."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import add_action
from tests.e2e.test_ui_catalog import _measure
from tests.helpers import connect, graph_url, node

NOTICE = "Guards are not available yet"


def _pipeline(client: httpx.Client, with_action: bool = False) -> dict[str, Any]:
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Watched"}).json()
    stage = node(client, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    if with_action:
        action = node(client, pipeline, "action", stage_id=stage["id"], x=60, y=48)
        connect(client, pipeline, stage, "start", action, "in")
    return pipeline


def _counts(api: httpx.Client, pipeline: dict[str, Any]) -> tuple[int, int]:
    graph = api.get(graph_url(pipeline)).json()
    return len(graph["nodes"]), len(graph["edges"])


def _open(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _notice(page: Page) -> None:
    expect(page.locator("[data-alert]")).to_be_visible()
    expect(page.locator("[data-alert]")).to_contain_text(NOTICE)
    assert page.locator("[data-alert]").get_attribute("role") == "alert", (
        "announced to screen readers"
    )


# ── the "+" menu of the canvas ───────────────────────────────────────────


def test_the_add_menu_holds_a_place_for_guards_after_pipeline_and_choosing_it_adds_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    nodes = page.locator(".ge-node")
    shown = nodes.count()

    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    items = page.locator(".ge-add__item")
    assert [i.split("\n")[0] for i in items.all_inner_texts()][:3] == ["Stage", "Pipeline", "Guard"]
    guard = page.locator("[data-placeholder=guard]")
    expect(guard).to_be_visible()
    expect(guard.locator("svg")).to_have_count(1)  # the shield
    expect(guard.locator(".tag")).to_have_text("Soon")
    assert guard.get_attribute("data-add") is None, "it is no kind: nothing can be added through it"

    guard.click()
    _notice(page)
    expect(page.locator("[data-add-list]")).to_be_hidden()
    expect(page.locator("[data-add-menu]")).to_be_focused()
    expect(nodes).to_have_count(shown)
    assert _counts(api, pipeline) == before, "nothing was saved"
    page.reload()
    expect(page.locator(".ge-node").first).to_be_visible()
    assert _counts(api, pipeline) == before


def test_a_guard_is_found_by_its_name_and_enter_chooses_it_like_any_entry(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "guard")
    expect(page.locator(".ge-add__item")).to_have_count(1)
    expect(page.locator("[data-placeholder=guard] .ge-add__tag")).to_have_text("Structure")
    page.keyboard.press("Enter")
    _notice(page)
    assert _counts(api, pipeline) == before


# ── the "+" of a stage ──────────────────────────────────────────────────


def test_the_plus_of_a_stage_opens_a_menu_with_action_and_guard(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    plus = page.locator("[data-stage-add]")
    expect(plus).to_have_accessible_name("Add to stage")
    assert plus.get_attribute("aria-haspopup") == "menu"
    assert plus.inner_text().strip() == "", "a plain plus: no word on the button"
    assert "icon-button" in (plus.get_attribute("class") or ""), "a catalog button (ADR-059)"

    plus.click()
    menu = page.get_by_role("menu", name="Add to stage")
    expect(menu).to_be_visible()
    entries = menu.get_by_role("menuitem")
    assert [e.split("\n")[0] for e in entries.all_inner_texts()] == ["Action", "Guard"]
    expect(entries.nth(1).locator(".tag")).to_have_text("Soon")
    expect(plus).to_have_attribute("aria-expanded", "true")


def test_action_in_the_stage_menu_adds_an_action_as_before_and_guard_adds_nothing(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    add_action(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)
    stage_id = next(
        n["id"] for n in api.get(graph_url(pipeline)).json()["nodes"] if n["kind"] == "stage"
    )
    saved = [n for n in api.get(graph_url(pipeline)).json()["nodes"] if n["kind"] == "action"]
    assert len(saved) == 1 and saved[0]["stage_id"] == stage_id, (
        "in this stage, as the old button did"
    )

    before = _counts(api, pipeline)
    page.locator("[data-stage-add]").click()
    page.get_by_role("menuitem", name="Guard").click()
    _notice(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)
    assert _counts(api, pipeline) == before


def test_the_plus_of_a_stage_works_with_the_keyboard(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    plus = page.locator("[data-stage-add]")
    plus.focus()
    page.keyboard.press("Enter")
    menu = page.get_by_role("menu", name="Add to stage")
    expect(menu.get_by_role("menuitem", name="Action", exact=True)).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Guard")).to_be_focused()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(plus).to_be_focused()
    page.keyboard.press("Space")
    expect(menu).to_be_visible()
    page.keyboard.press("Enter")  # the first entry: Action
    expect(page.locator(".ge-node--action")).to_have_count(1)


# ── an action ────────────────────────────────────────────────────────────


def test_the_menu_of_an_action_node_offers_guard_before_delete(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--action .ge-node__name").click(button="right")
    menu = page.get_by_role("menu")
    labels = [e.split("\n")[0] for e in menu.get_by_role("menuitem").all_inner_texts()]
    assert labels.index("Guard") == len(labels) - 2 and labels[-1] == "Delete", labels
    expect(menu.get_by_role("menuitem", name="Guard").locator(".tag")).to_have_text("Soon")
    menu.get_by_role("menuitem", name="Guard").click()
    _notice(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)
    assert _counts(api, pipeline) == before


def test_a_stage_and_a_trigger_have_no_guard_in_their_node_menu(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator(".ge-node--trigger .ge-node__name").click(button="right")
    expect(page.get_by_role("menu").get_by_role("menuitem", name="Guard")).to_have_count(0)
    page.keyboard.press("Escape")


def test_the_add_menu_inside_an_action_definition_has_the_guard_place_too(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    before = _counts(api, definition)
    _open(page, base_url, f"/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    guard = page.locator("[data-placeholder=guard]")
    expect(guard.locator(".tag")).to_have_text("Soon")
    guard.click()
    _notice(page)
    assert _counts(api, definition) == before


# ── language, look ───────────────────────────────────────────────────────


def test_the_place_is_named_in_german_and_its_tag_is_readable(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator("[data-stage-add]").click()
    guard = page.get_by_role("menuitem", name="Guard")
    expect(guard.locator(".tag")).to_have_text("Bald")
    guard.click()
    expect(page.locator("[data-alert]")).to_contain_text("Guards gibt es noch nicht")
    for theme in ("light", "dark"):
        page.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
        page.locator("[data-stage-add]").click()
        ratio = _measure(page, page.locator(".menu .tag"))["text"]
        assert ratio >= 4.5, f"{theme}: the Soon tag has a contrast of {ratio:.2f}"
        page.keyboard.press("Escape")

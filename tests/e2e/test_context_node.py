"""The Build Context node in the browser (ADR-078): its sources are an ordered list, and a step says what went into its package."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually, execution_of, flow_url, run_started
from tests.helpers import build_definition, build_pipeline, connect, graph_url, kind_of, link, node


def _sources(api: httpx.Client, definition: dict[str, Any]) -> Any:
    found = next(
        n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "context"
    )
    return found["config"].get("sources")


def _config(api: httpx.Client, definition: dict[str, Any]) -> dict[str, Any]:
    found = next(
        n for n in api.get(graph_url(definition)).json()["nodes"] if n["kind"] == "context"
    )
    config: dict[str, Any] = found["config"]
    return config


def _dialog(page: Page) -> None:
    page.locator(".ge-node--context").dblclick(position={"x": 30, "y": 5})
    expect(page.locator("#node-modal")).to_be_visible()


def test_the_sources_are_a_list_that_is_added_to_ordered_edited_and_kept(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Package check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "Build")
    page.click("[data-add=context]")
    card = page.locator(".ge-node--context")
    expect(card).to_contain_text("Build Context")
    expect(card).to_contain_text("Title and body, Comments")  # the caption names the sources
    _dialog(page)
    rows = page.locator("#node-modal .ge-source")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).locator(".ge-source__name")).to_have_text("Title and body")
    expect(rows.nth(1).locator(".ge-source__name")).to_have_text("Comments")
    expect(rows.nth(1).locator(".ge-source__count")).to_have_value("20")
    size_row = page.locator("#node-modal").get_by_label("Size limit", exact=True)
    expect(size_row).to_have_value(
        "8"
    )  # 8 KiB, typed in a unit like the output limit of Execute Command
    expect(page.locator("#node-modal .size-input select").first).to_have_value("KiB")

    # add a source: the select offers only what is not in the list yet
    add = page.locator("#node-modal .ge-sources__add")
    options = add.locator("option").all_inner_texts()
    assert (
        "Title and body" not in options and "Comments" not in options and "Parent card" in options
    )
    add.select_option(label="Parent card")
    expect(rows).to_have_count(3)
    eventually(
        lambda: _sources(api, definition),
        [{"source": "card"}, {"source": "comments", "count": 20}, {"source": "parent", "detail": "title"}],
    )  # fmt: skip

    # the order is the priority: the handle moves a row with the arrow keys, and the new order is stored
    grip = rows.nth(2).locator(".ge-source__grip")
    grip.focus()
    page.keyboard.press("ArrowUp")
    expect(rows.nth(1).locator(".ge-source__name")).to_have_text("Parent card")
    expect(rows.nth(1).locator(".ge-source__grip")).to_be_focused()  # the focus follows the row
    eventually(
        lambda: [s["source"] for s in _sources(api, definition)], ["card", "parent", "comments"]
    )

    # an option of a source: title only, or title and text
    rows.nth(1).locator(".ge-source__detail").select_option(label="Title and text")
    eventually(lambda: _sources(api, definition)[1], {"source": "parent", "detail": "text"})

    # a number outside the bounds says why and sends nothing
    count = rows.nth(2).locator(".ge-source__count")
    count.fill("0")
    count.press("Enter")
    expect(page.locator("#node-modal").get_by_role("alert").first).to_contain_text(
        "Comments: the number of items is 1 to 100."
    )
    assert _sources(api, definition)[2] == {"source": "comments", "count": 20}
    count.fill("5")
    count.press("Enter")
    eventually(lambda: _sources(api, definition)[2], {"source": "comments", "count": 5})

    # the bin takes a source out, the list is kept after a reload
    rows.nth(0).locator(".ge-source__bin").click()
    eventually(lambda: [s["source"] for s in _sources(api, definition)], ["parent", "comments"])
    page.keyboard.press("Escape")
    page.reload()
    _dialog(page)
    names = page.locator("#node-modal .ge-source .ge-source__name")
    expect(names).to_have_text(["Parent card", "Comments"])
    expect(
        page.locator("#node-modal .ge-source").nth(0).locator(".ge-source__detail")
    ).to_have_value("text")


def test_the_size_limit_is_typed_in_a_unit_and_kept_in_bytes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition: dict[str, Any] = api.post("/api/actions", json={"name": "Limit check"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "Build")
    page.click("[data-add=context]")
    _dialog(page)
    field = page.locator("#node-modal .size-input").filter(
        has=page.get_by_label("Size limit", exact=True)
    )
    number, unit = field.locator("input"), field.locator("select")
    number.fill("16")
    number.press("Enter")
    eventually(lambda: _config(api, definition).get("size_limit"), 16384)
    number.fill("40")  # more than the 32 KiB a package may take
    number.press("Enter")
    expect(page.locator("#node-modal").get_by_role("alert").first).to_contain_text(
        "from 1 KiB to 32 KiB"
    )
    assert _config(api, definition).get("size_limit") == 16384  # refused: nothing was sent
    number.fill("1500")
    unit.select_option("B")
    eventually(lambda: _config(api, definition).get("size_limit"), 1500)


def _package_pipeline(api: httpx.Client) -> tuple[dict[str, Any], dict[str, Any]]:
    """A card with a parent and three long comments, and an action that builds a package of its comments, card and children
    within the smallest limit: the comments do not all fit, the card has no children."""
    parent: dict[str, Any] = api.post("/api/tasks", json={"title": "Epic"}).json()
    task: dict[str, Any] = api.post(
        "/api/tasks", json={"title": "Fix the login", "parent_id": parent["id"]}
    ).json()
    for i in range(1, 6):
        api.post(f"/api/tasks/{task['id']}/comments", json={"body": f"comment {i} " + "x" * 400})
    definition = build_definition(api, "Package", output=None, fail_enabled=True)
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    step = node(
        api, definition, "context", name="Package",
        config={
            "sources": [
                {"source": "comments", "count": 10},
                {"source": "card"},
                {"source": "children"},
            ],
            "size_limit": 1024,
        },
    )  # fmt: skip
    connect(api, definition, trigger, "out", step, "in")
    connect(api, definition, step, "pass", output, "pass")
    connect(api, definition, step, "fail", output, "fail")
    pipeline = build_pipeline(api, stages=1, name="Package flow", stage_name="Build")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    return task, pipeline


def test_a_step_lists_what_went_into_the_package_and_what_was_left_out(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    task, pipeline = _package_pipeline(api)
    run_started(api, task, pipeline)
    page.goto(flow_url(base_url, task, execution_of(api, task)))
    page.locator(".ge-node--action").first.click()
    page.locator(".ef-path__item").filter(has_text="package").locator(".ef-path__main").click()
    detail = page.locator("[data-panel-detail]")
    expect(detail).to_contain_text(
        re.compile(r"Package \d+(\.\d)? (B|KiB) of 1\.0 KiB \(about \d+ tokens\)")
    )  # how full it is, with the approximate tokens
    box = detail.locator("[data-step-context]")
    expect(box.locator("[data-step-context-title]")).to_have_text("In the package")
    included = box.locator("[data-step-context-included] li")
    expect(included).to_have_count(2)
    expect(included.nth(0)).to_contain_text(
        "Comments: 2 of 5"
    )  # the newest two fit next to the card
    expect(included.nth(1)).to_contain_text("Title and body: 1 in all")
    expect(box.locator("[data-step-context-omitted-title]")).to_have_text("Left out")
    expect(box.locator("[data-step-context-omitted] li")).to_have_text(
        ["Child cards: the card has no child cards"]
    )
    detail.locator("[data-step-output] summary").click()
    expect(detail.locator("[data-step-output] pre")).to_contain_text(
        "[... 3 older comments left out]"
    )

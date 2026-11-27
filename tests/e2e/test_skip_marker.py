"""A node a dry run skipped is drawn like one that ran and carries the skip marker (ADR-086 addendum 3).

The flow page used to treat a skipped step like any passed one without saying that nothing was done. Dimmed means "not reached" (a dashed outline); a
skipped node was passed in the flow, so it keeps its colour and gets the "skip forward" icon with what it would have done as its tooltip. A node that
handed over a mock was processed, so it has no such marker."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually
from tests.e2e.test_icon_list_glyphs import _centred, _measure
from tests.helpers import connect, graph_url, kind_of, node, post

MARK = "[data-skip-marker]"


def _action(api: httpx.Client) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """trigger -> Timer 'Wait' -> Artifact 'Comment' (skipped: it writes) -> Artifact 'Mocked' (a mock stands in) -> output; 'Never' hangs on the
    error output of 'Comment', which is not taken."""
    action = post(api, "/api/actions", name="Skips")
    trigger, output = kind_of(api, action, "trigger"), kind_of(api, action, "output")
    for edge in api.get(graph_url(action)).json()["edges"]:
        api.delete(f"{graph_url(action)}/edges/{edge['id']}")
    wait = node(api, action, "timer", name="Wait", seconds=3, x=300, y=40)
    comment = node(
        api,
        action,
        "artifact",
        name="Comment",
        config={"operation": "Add comment", "text": "hi"},
        x=600,
        y=40,
    )
    mocked = node(
        api,
        action,
        "artifact",
        name="Mocked",
        config={"operation": "Add comment", "text": "hi again"},
        x=900,
        y=40,
    )
    never = node(api, action, "set", name="Never", config={"fields": "x = 1"}, x=750, y=260)
    connect(api, action, trigger, "out", wait, "in")
    connect(api, action, wait, "out", comment, "in")
    connect(api, action, comment, "pass", mocked, "in")
    connect(api, action, comment, "fail", never, "in")
    connect(api, action, mocked, "pass", output, "pass")
    api.patch(
        f"{graph_url(action)}/nodes/{mocked['id']}",
        json={
            "mock": {"enabled": True, "outcome": "pass", "output": "created #7", "data": {"id": 7}}
        },
    ).raise_for_status()
    return action, {"wait": wait, "comment": comment, "mocked": mocked, "never": never}


def _dry_run_page(page: Page, base_url: str, api: httpx.Client) -> dict[str, dict[str, Any]]:
    action, nodes = _action(api)
    started = api.post(f"/api/graphs/{action['id']}/dry-run", json={})
    assert started.status_code == 201, started.text
    task_id = started.json()["task_id"]
    eventually(
        lambda: api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]["status"], "done"
    )
    execution = api.get(f"/api/tasks/{task_id}/executions").json()["items"][0]
    number = api.get(f"/api/tasks/{task_id}").json()["number"]
    page.set_viewport_size({"width": 1500, "height": 900})
    page.goto(f"{base_url}/artifacts/{number}/executions/{execution['id']}")
    expect(page.locator("[data-head-chip]")).to_have_text("Done")
    return nodes


def _card(page: Page, nodes: dict[str, dict[str, Any]], key: str) -> Any:
    return page.locator(f'.ef-viewport .ge-node[data-node-id="{nodes[key]["id"]}"]')


def test_a_skipped_node_is_drawn_as_passed_with_the_marker_and_what_it_would_have_done(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    nodes = _dry_run_page(page, base_url, api)
    for key, what in (
        ("wait", "would have waited 3 s"),
        ("comment", "would have added this comment to the artifact: hi"),
    ):
        card = _card(page, nodes, key)
        expect(card).not_to_have_class(
            re.compile(r"\bis-dim\b")
        )  # passed in the flow: not the dashed, faded look of a node that was not reached
        marker = card.locator(MARK)
        expect(marker).to_have_count(1)
        expect(marker).to_have_attribute("aria-label", f"Skipped in a dry run: {what}")
        marker.hover()
        expect(page.get_by_role("tooltip")).to_contain_text(f"Skipped in a dry run: {what}")
        page.mouse.move(0, 0)


def test_the_marker_is_a_shape_in_the_cards_icon_list_and_centred_in_its_hover_box(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    nodes = _dry_run_page(page, base_url, api)
    marker = _card(page, nodes, "wait").locator(f"{MARK}")
    expect(marker.locator("svg")).to_have_count(1)
    expect(marker).to_have_class(re.compile(r"icon-button--quiet"))
    assert marker.evaluate("el => el.parentElement.classList.contains('ge-node__icons')")
    marker.focus()
    expect(marker).to_be_focused()  # reachable by the keyboard
    measured = _measure(
        page, marker
    )  # the rule of every icon list: the glyph is centred in its square, normal and hover
    _centred("skip marker", measured)
    assert (
        abs(measured["normal"]["width"] - measured["normal"]["height"]) < 0.01
    )  # a square (the flow page scales the card to fit: not 24 px)


def test_a_mocked_node_has_no_skip_marker_and_a_node_that_was_not_reached_stays_faded(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    nodes = _dry_run_page(page, base_url, api)
    mocked = _card(page, nodes, "mocked")
    expect(mocked).not_to_have_class(re.compile(r"\bis-dim\b"))
    expect(mocked.locator(MARK)).to_have_count(
        0
    )  # processed with the mock data, not skipped: the two never meet on a node
    never = _card(page, nodes, "never")
    expect(never).to_have_class(re.compile(r"\bis-dim\b"))
    expect(never.locator(MARK)).to_have_count(0)
    # the mocked node says so in its step
    mocked.click()
    expect(page.locator(".history-step [data-step-mock]:not([hidden])")).to_be_visible()
    expect(page.locator(".history-step [data-step-skip] [data-skip-marker]")).to_have_count(0)


def test_the_path_list_and_the_step_detail_show_the_marker_of_a_skipped_step(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    nodes = _dry_run_page(page, base_url, api)
    skipped = page.locator(".ef-path__item", has=page.locator(".ef-path__skip"))
    expect(skipped).to_have_count(
        2
    )  # the timer and the comment; neither the mocked node nor the trigger and the output
    expect(skipped.first.locator(".ef-path__skip")).to_have_attribute(
        "title", "Skipped in a dry run: would have waited 3 s"
    )
    expect(skipped.first.locator(".ef-path__main")).to_have_attribute(
        "aria-label", re.compile("Skipped in a dry run: would have waited 3 s")
    )
    _card(page, nodes, "comment").click()
    detail = page.locator(".history-step [data-step-skip]:not([hidden])")
    expect(detail.locator(MARK)).to_have_attribute(
        "aria-label", "Skipped in a dry run: would have added this comment to the artifact: hi"
    )
    # the step keeps its wording
    expect(page.locator(".history-step__reason")).to_contain_text("would have added this comment")

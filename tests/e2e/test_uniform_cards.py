"""The cards of the four management pages have one fixed size and one arrangement (ADR-069 addendum): the same width and height
whatever the title and the text are, the title up to two lines and then cut with "…" before the pencil and the bin, the grid never
stretches a card and starts a new row only when the room is gone."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.helpers import post

LONG = "A very long name that goes on and on and on and on and on and on and on for more than two lines"
WORD = "Unbroken" * 11  # a title of one long word must not widen the card either


def _actions(api: httpx.Client) -> None:
    post(
        api,
        "/api/actions",
        name=LONG,
        description="A text that is long enough to need its two lines and a bit more, " * 3,
    )
    post(api, "/api/actions", name="Short")
    post(api, "/api/actions", name=WORD, description="Described")


def _pipelines(api: httpx.Client) -> None:
    post(
        api,
        "/api/pipelines",
        name=LONG,
        description="A text that is long enough to need its two lines and a bit more, " * 3,
    )
    post(api, "/api/pipelines", name="Short")
    post(api, "/api/pipelines", name=WORD, description="Described")


def _agents(api: httpx.Client) -> None:
    # the server is shared by the tests of a worker: agents other tests left would be more cards than these three
    for left in api.get("/api/agents").json():
        api.delete(f"/api/agents/{left['id']}")
    for name, extra in (
        (LONG, {"description": "A text long enough for two lines and more " * 4}),
        ("Short", {}),
        (WORD, {"description": "Described"}),
    ):
        made = api.post(
            "/api/agents", json={"name": name, "draft": {"user_prompt": "Say hi."}, **extra}
        )
        if (
            made.status_code != 409
        ):  # the server is shared by the tests of a session: the agent may exist already
            made.raise_for_status()


def _guards(api: httpx.Client) -> None:
    body = {"trigger": {"type": "event", "events": ["enter"]}, "consequence": "pause"}
    for name in (LONG, "Short", WORD):
        api.post("/api/guards", json={"name": name, **body}).raise_for_status()


PAGES: list[tuple[str, Callable[[httpx.Client], None]]] = [
    ("/actions", _actions),
    ("/pipelines", _pipelines),
    ("/agents", _agents),
    ("/guards", _guards),
]


def _boxes(page: Page, selector: str) -> list[dict[str, float]]:
    return [b for b in (el.bounding_box() for el in page.locator(selector).all()) if b]


@pytest.mark.parametrize(("path", "make"), PAGES, ids=[p for p, _ in PAGES])
def test_every_card_has_the_same_size_whatever_it_holds_and_a_long_title_is_cut_before_the_buttons(
    page: Page, base_url: str, api: httpx.Client, path: str, make: Callable[[httpx.Client], None]
) -> None:
    make(api)
    page.set_viewport_size({"width": 1700, "height": 900})
    page.goto(f"{base_url}{path}")
    cards = page.locator(".mg-card")
    expect(cards).to_have_count(3)
    boxes = _boxes(page, ".mg-card")
    assert {round(b["width"]) for b in boxes} == {round(boxes[0]["width"])}, (
        f"one width: {[b['width'] for b in boxes]}"
    )
    assert {round(b["height"]) for b in boxes} == {round(boxes[0]["height"])}, (
        f"one height: {[b['height'] for b in boxes]}"
    )
    rem = page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)")
    assert abs(boxes[0]["width"] - 19 * rem) <= 2, (
        "the standard width (19 rem), not stretched by the grid"
    )
    assert abs(boxes[0]["height"] - 11 * rem) <= 2, (
        f"the standard height (11 rem, measured on the owner's draft): {boxes[0]['height'] / rem} rem"
    )
    for card in cards.all():
        # the content of even the fullest card (two lines of title and of text, the chips, the facts, the date) stays inside it:
        # nothing is cut off at the bottom and the row of chips is one row, not wrapped
        assert card.evaluate("el => el.scrollHeight <= el.clientHeight + 1"), (
            "nothing runs out of the card"
        )
        chips = card.locator(".mg-card__chips")
        if chips.count():
            assert chips.evaluate(
                "el => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().height < 2.2 * parseFloat(getComputedStyle(el).fontSize)"
            ), "the chips stand in ONE row"
        last = card.locator(".mg-card__date, .mg-card__facts").last
        if last.count():
            box = last.bounding_box()
            assert (
                box
                and box["y"] + box["height"]
                <= card.bounding_box()["y"] + card.bounding_box()["height"] + 1
            ), (  # type: ignore[index]
                "the last line (the date) is not cut off"
            )
        text_right = card.locator(".mg-card__name").evaluate(
            "el => el.getBoundingClientRect().right - parseFloat(getComputedStyle(el).paddingRight)"
        )
        actions = card.locator(".mg-card__actions").bounding_box()
        assert actions
        assert text_right <= actions["x"] + 1, (
            "the title's text stays left of the pencil and the bin"
        )
        assert (
            card.locator(".mg-card__foot").bounding_box()["y"]
            + card.locator(".mg-card__foot").bounding_box()["height"]
            <= card.bounding_box()["y"] + card.bounding_box()["height"] + 1
        ), "the foot stays inside the card"  # type: ignore[index]
    long_name = page.locator(".mg-card__name", has_text="A very long name").first
    assert long_name.evaluate("el => el.scrollHeight > el.clientHeight"), (
        "a title of more than two lines is cut"
    )
    assert long_name.evaluate("el => getComputedStyle(el).webkitLineClamp") == "2", (
        "after two lines, with an ellipsis"
    )
    assert long_name.evaluate(
        "el => el.getBoundingClientRect().height <= 2.7 * parseFloat(getComputedStyle(el).fontSize)"
    )


@pytest.mark.parametrize(("path", "make"), PAGES[:1] + PAGES[2:3], ids=["/actions", "/agents"])
def test_the_grid_starts_a_new_row_only_when_the_room_is_gone_and_never_stretches_a_card(
    page: Page, base_url: str, api: httpx.Client, path: str, make: Callable[[httpx.Client], None]
) -> None:
    make(api)
    widths: dict[int, tuple[int, float]] = {}
    for viewport in (1900, 1500, 1200):
        page.set_viewport_size({"width": viewport, "height": 900})
        page.goto(f"{base_url}{path}")
        expect(page.locator(".mg-card")).to_have_count(3)
        boxes = _boxes(page, ".mg-card")
        per_row = len([b for b in boxes if abs(b["y"] - boxes[0]["y"]) < 2])
        widths[viewport] = (per_row, boxes[0]["width"])
    assert len({w for _, w in widths.values()}) == 1, f"the card keeps its width: {widths}"
    assert widths[1900][0] >= widths[1200][0], "fewer beside each other on a narrower screen"
    assert widths[1900][0] == 3 or widths[1500][0] >= 2, (
        f"three cards stand beside each other where the room holds them: {widths}"
    )


def test_the_editor_marks_draft_or_published_beside_the_way_back_and_follows_every_change(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """ "Draft" while nothing is published or the draft differs, "v1 published" while they are equal; it changes as soon as something is
    changed in the editor, and again when the tab is asked after a publication (that happens on the management page)."""
    from tests.e2e.helpers import pick_node

    action = post(api, "/api/actions", name="Marked")
    page.goto(f"{base_url}/actions/{action['slug']}")
    mark = page.locator(".ge-bar__state")
    expect(mark).to_have_text("Draft")
    back = page.locator(".ge-bar a", has_text="All actions").bounding_box()
    box = mark.bounding_box()
    assert back and box and box["x"] > back["x"] + back["width"] - 1, (
        "right beside the way back, left of the zoom buttons"
    )
    assert box["x"] < back["x"] + back["width"] + 200
    api.post(f"/api/actions/{action['id']}/publish").raise_for_status()
    page.reload()
    expect(mark).to_have_text("v1 published")
    expect(mark.locator(".mg-chip")).to_have_attribute("data-publication", "published")
    # a change in the editor turns it to Draft (the version in use stays 1: the tooltip says so)
    page.click("[data-add-menu]")
    pick_node(page, "code")
    expect(mark).to_have_text("Draft")
    assert "version 1" in (mark.locator(".mg-chip").get_attribute("title") or "")
    # publishing happens elsewhere: the tab asks again when it is back
    api.post(f"/api/actions/{action['id']}/publish").raise_for_status()
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(mark).to_have_text("v2 published")

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
    for card in cards.all():
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

"""The glyph of every entry of a flexible icon list sits in the CENTRE of its square hit area, in the normal and in the hover state: the pin and the shield on a
node card (24 px buttons) and the eye, the shield and the plus in the canvas corner. The browser's own button padding (1px 6px) was wider than the content of
a 24 px button, so the 16 px glyph overflowed to the right and sat 3 px off the centre; `.icon-button` has no padding of its own now. One rule for every variant of
the list (components/icon-list.js)."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_card_icons import NAME, _node_id, _set_mock
from tests.e2e.test_guard_scopes import _action, _attach_to
from tests.e2e.test_guards import _guard, _open
from tests.e2e.test_observe_ui import _guard_on_the_pipeline, _observe, _pipeline

# the box of the button, the box of its svg and the centre of what the svg draws (its content box mapped through the viewBox)
GLYPH = """(button) => {
  const b = button.getBoundingClientRect();
  const svg = button.querySelector('svg');
  const s = svg.getBoundingClientRect();
  const box = svg.getBBox();
  const vb = svg.viewBox.baseVal;
  const kx = s.width / (vb.width || s.width);
  const ky = s.height / (vb.height || s.height);
  const cx = s.x + (box.x + box.width / 2 - vb.x) * kx;
  const cy = s.y + (box.y + box.height / 2 - vb.y) * ky;
  return {
    width: b.width, height: b.height,
    svgDx: s.x + s.width / 2 - (b.x + b.width / 2), svgDy: s.y + s.height / 2 - (b.y + b.height / 2),
    glyphDx: cx - (b.x + b.width / 2), glyphDy: cy - (b.y + b.height / 2),
    glyphW: box.width * kx, glyphH: box.height * ky,
    tint: getComputedStyle(button).backgroundColor,
  };
}"""


def _measure(page: Page, button: Locator) -> dict[str, Any]:
    expect(button).to_be_visible()
    page.mouse.move(2, 2)
    page.wait_for_timeout(300)
    normal = button.evaluate(GLYPH)
    button.hover()
    page.wait_for_timeout(700)  # the tint is a transition
    hover = button.evaluate(GLYPH)
    page.mouse.move(2, 2)
    return {"normal": normal, "hover": hover}


def _centred(name: str, measured: dict[str, Any]) -> None:
    for state in ("normal", "hover"):
        m = measured[state]
        assert abs(m["svgDx"]) <= 1 and abs(m["svgDy"]) <= 1, (
            name,
            state,
            "the icon box is centred in the button",
            m,
        )
        assert abs(m["glyphDx"]) <= 1 and abs(m["glyphDy"]) <= 1, (
            name,
            state,
            "what is drawn is centred in the button",
            m,
        )
    assert measured["normal"]["width"] == measured["hover"]["width"], (
        name,
        "the hit area does not change on hover",
    )
    assert measured["normal"]["tint"] != measured["hover"]["tint"], (name, "the hover shows a tint")


def test_the_pin_and_the_shield_on_a_card_are_centred_in_their_square_and_the_same_size(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    node_id = _node_id(api, action)
    _set_mock(api, action, node_id)
    _attach_to(api, _guard(api, "Centre guard"), action, "node", node_id)
    _open(page, base_url, f"/actions/{action['slug']}")
    card = page.locator(".ge-node", has_text=NAME).first
    pin = _measure(page, card.locator("[data-mock-pin]"))
    shield = _measure(page, card.locator("[data-guard-shield]"))
    _centred("pin", pin)
    _centred("shield", shield)
    assert pin["normal"]["width"] == shield["normal"]["width"] == 24
    assert pin["normal"]["height"] == shield["normal"]["height"] == 24, (
        "a square hit area, both the same"
    )
    assert abs(pin["normal"]["glyphH"] - shield["normal"]["glyphH"]) <= 2, (
        "the two glyphs are about the same height"
    )


def test_the_eye_the_shield_and_the_plus_of_the_canvas_corner_are_centred_in_their_square(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _observe(api, pipeline)
    _guard_on_the_pipeline(api, pipeline)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator('[data-status-entry="guard"]')).to_be_visible()
    for key in ("observe", "guard", "add"):
        measured = _measure(page, page.locator(f'[data-status-entry="{key}"]'))
        _centred(key, measured)
        assert measured["normal"]["width"] == measured["normal"]["height"], (
            key,
            "a square hit area",
        )

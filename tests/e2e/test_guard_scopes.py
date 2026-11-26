"""Guards on an action definition and on its nodes (ADR-060 addendum), and the popup's two layouts: the action editor's "+"
offers Guard and its shield sits next to the "+", a guardable node (not the trigger, not the output) has the Guard entry in its
menu and a bare shield in its top right corner, the card of an action in a pipeline mirrors the guards inside its
definition ("In the action"), and the popup's buttons stack when it opens from a stage header or a card and sit side by
side everywhere else."""

from __future__ import annotations

from typing import Any, cast

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import code_definition
from tests.e2e.test_guards import (
    DASH,
    _attach,
    _attach_through_dialog,
    _guard,
    _open,
    _pipeline,
    _popup,
    _window,
)
from tests.helpers import graph_url, link, node


def _box(el: Locator) -> dict[str, float]:
    box = el.bounding_box()
    assert box is not None
    return cast(dict[str, float], box)


def _attach_to(
    api: httpx.Client,
    guard: dict[str, Any],
    holder: dict[str, Any],
    scope: str,
    scope_id: str | None,
) -> dict[str, Any]:
    response = api.post(
        "/api/guard-attachments",
        json={
            "guard_id": guard["id"],
            "graph_id": holder["id"],
            "scope_type": scope,
            "scope_id": scope_id,
        },
    )
    response.raise_for_status()
    attachment: dict[str, Any] = response.json()
    return attachment


def _action(api: httpx.Client, name: str = "Summarise") -> dict[str, Any]:
    """An action definition: trigger -> a Code node (named like the action) -> output, plus an unconnected Agent node."""
    definition = code_definition(api, name, "print('ok')", node_name=f"{name} code")
    node(api, definition, "agent", name="Judge", x=420, y=260)
    return definition


def _menu_entries(page: Page) -> list[str]:
    return [t.split("\n")[0] for t in page.get_by_role("menuitem").all_inner_texts()]


# ── the popup's layouts ──────────────────────────────────────────────


def test_the_add_popup_stacks_its_buttons_from_a_stage_header_and_a_card_and_not_from_the_canvas_plus(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    _guard(api, "Round guard")
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    layouts = {}
    for where in ("canvas", "stage", "card"):
        if where == "canvas":
            page.click("[data-add-menu]")
            page.locator('.ge-add__group[data-group="Structure"]').click()
            page.locator("[data-placeholder=guard]").click()
        elif where == "stage":
            page.locator("[data-stage-add]").click()
            page.get_by_role("menuitem", name="Guard").click()
        else:
            page.locator(".ge-node--action", has_text="Draft").click(button="right")
            page.get_by_role("menuitem", name="Guard").click()
        popup = _popup(page)
        attach = _box(popup.get_by_role("button", name="Attach guard"))
        new = _box(popup.get_by_role("button", name="New guard"))
        layouts[where] = (attach, new, _box(popup))
        page.keyboard.press("Escape")
        expect(popup).to_be_hidden()
    attach, new, _ = layouts["canvas"]
    assert new["x"] > attach["x"] + attach["width"] - 1 and abs(new["y"] - attach["y"]) < 2, (
        "side by side"
    )
    for where in ("stage", "card"):
        attach, new, popup = layouts[where]
        assert new["y"] >= attach["y"] + attach["height"] - 1, f"{where}: stacked"
        assert abs(new["x"] - attach["x"]) < 2, f"{where}: same column"
        # no long empty bar: each button is as wide as its own content and the popup as wide as its widest
        # button plus its padding (this popup holds nothing else)
        widest = max(attach["width"], new["width"])
        assert widest < 200, f"{where}: content-sized buttons ({widest}px)"
        assert popup["width"] <= widest + 40, (
            f"{where}: popup {popup['width']}px for buttons of {widest}px"
        )


# ── the action editor ────────────────────────────────────────────────


def test_the_action_editors_plus_offers_guard_and_the_shield_appears_next_to_it_at_the_top_right(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    nodes_before = len(api.get(graph_url(action)).json()["nodes"])
    _guard(api, "Stall guard")
    _open(page, base_url, f"/actions/{action['slug']}")
    shield = page.locator("[data-pipeline-shield]")
    expect(shield).to_be_hidden()
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    page.locator("[data-placeholder=guard]").click()
    popup = _popup(page)
    expect(popup).to_have_accessible_name("Add a guard")
    _attach_through_dialog(page, "Stall")
    expect(shield).to_be_visible()
    expect(shield).to_have_attribute("title", "1 guard configured")
    plus, field = _box(page.locator("[data-add-menu]")), _box(page.locator("[data-viewport]"))
    shield_box = _box(shield)
    assert shield_box["x"] < plus["x"] and abs(shield_box["y"] - plus["y"]) < 4, "next to the plus"
    assert plus["x"] + plus["width"] > field["x"] + field["width"] - 60, "top right of the canvas"
    [place] = api.get("/api/guard-attachments", params={"pipeline_id": action["id"]}).json()
    assert (place["scope_type"], place["scope_id"], place["holder_kind"]) == (
        "definition",
        action["id"],
        "action",
    )
    assert len(api.get(graph_url(action)).json()["nodes"]) == nodes_before, (
        "a guard is never a node"
    )


def test_a_guardable_node_has_the_guard_entry_and_a_bare_shield_and_the_trigger_and_output_have_neither(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _action(api)
    _guard(api, "Stall guard")
    _open(page, base_url, f"/actions/{action['slug']}")
    for name in ("Summarise code", "Judge"):  # a Code node and an Agent node
        page.locator(".ge-node", has_text=name).first.click(button="right")
        assert "Guard" in _menu_entries(page), name
        page.keyboard.press("Escape")
    for kind in ("Trigger", "Output"):
        card = page.locator(".ge-node", has_text=kind).first
        card.click(button="right")
        assert "Guard" not in _menu_entries(page), kind
        page.keyboard.press("Escape")
    page.locator(".ge-node", has_text="Summarise code").first.click(button="right")
    page.get_by_role("menuitem", name="Guard").click()
    _attach_through_dialog(page, "Stall")
    card = page.locator(".ge-node", has_text="Summarise code").first
    shield = card.locator("[data-guard-shield]")
    expect(shield).to_be_visible()
    expect(shield).to_have_attribute("title", "1 guard configured")
    style = shield.evaluate(
        "el => { const s = getComputedStyle(el); return [s.borderTopColor, s.backgroundColor, el.offsetWidth, el.offsetHeight]; }"
    )
    transparent = ("rgba(0, 0, 0, 0)", "transparent")
    assert style[0] in transparent and style[1] in transparent, "no frame, no fill"
    assert style[2] >= 24 and style[3] >= 24, "a hit area"
    cb, sb = _box(card), _box(shield)
    assert sb["x"] + sb["width"] > cb["x"] + cb["width"] - 10 and sb["y"] < cb["y"] + 10, (
        "top right corner of the card"
    )
    [place] = api.get("/api/guard-attachments", params={"pipeline_id": action["id"]}).json()
    assert place["scope_type"] == "node" and place["scope_name"] == "Summarise code"
    other = page.locator(".ge-node", has_text="Judge").first
    expect(other.locator("[data-guard-shield]")).to_have_count(0)


# ── the pipeline mirrors what sits inside an action ──────────────────


def test_an_action_card_mirrors_the_guards_inside_its_definition_and_opens_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    action = _action(api)
    link(api, pipeline, pipeline["action"], action)
    code = next(n for n in api.get(graph_url(action)).json()["nodes"] if n["kind"] == "code")
    inner = _guard(api, "Inner stall")
    whole = _guard(api, "Whole action")
    own = _guard(api, "Own guard")
    _attach_to(api, inner, action, "node", code["id"])
    _attach_to(api, whole, action, "definition", None)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    card = page.locator(".ge-node--action", has_text="Summarise").first
    shield = card.locator("[data-guard-shield]")
    expect(shield).to_be_visible()  # the card has no guard of its own: it counts the two inside
    expect(shield).to_have_attribute("title", "2 guards configured")
    _attach(api, own, pipeline, "action", pipeline["action"]["id"])
    page.reload()
    expect(
        page.locator(".ge-node--action", has_text="Summarise").first.locator("[data-guard-shield]")
    ).to_have_attribute("title", "3 guards configured")
    page.locator(".ge-node--action", has_text="Summarise").first.locator(
        "[data-guard-shield]"
    ).click()
    popup = _popup(page)
    assert popup.locator(".gd-popover__attached .gd-attached__name").all_inner_texts() == [
        "Own guard"
    ]
    inside = popup.locator(".gd-popover__inner li")
    assert [t.replace("\n", " | ") for t in inside.all_inner_texts()] == [
        "Inner stall | Node Summarise code",
        "Whole action | The whole action",
    ]
    assert (
        popup.locator(".gd-popover__inner .gd-switch, .gd-popover__inner [data-detach]").count()
        == 0
    ), "no detach inside"
    link_el = popup.locator("[data-open-action]")
    assert f"/actions/{action['id']}" in (link_el.get_attribute("href") or "")
    popup.locator(".gd-popover__inner .gd-attached__name", has_text="Inner stall").click()
    window = _window(page)
    expect(window.locator(".modal__title")).to_have_text(f"Guard {DASH} Inner stall")


def test_the_mirrored_popup_speaks_german(page: Page, base_url: str, api: httpx.Client) -> None:
    pipeline = _pipeline(api, with_action=True)
    action = _action(api)
    link(api, pipeline, pipeline["action"], action)
    _attach_to(api, _guard(api, "Inner stall"), action, "definition", None)
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    shield = page.locator(".ge-node--action", has_text="Summarise").first.locator(
        "[data-guard-shield]"
    )
    expect(shield).to_have_attribute("title", "1 Wächter eingerichtet")
    shield.click()
    popup = _popup(page)
    expect(popup).to_contain_text("In der Aktion")
    expect(popup).to_contain_text("Die ganze Aktion")
    expect(popup.locator("[data-open-action]")).to_have_text("Aktion öffnen")

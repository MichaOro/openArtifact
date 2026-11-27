"""The two looks the owner asked for after testing ADR-082/083: the name of a numbered placement on its card (the number first and quiet, the
name cut with an ellipsis before the port labels) and the field list of the Trigger, Output and Complete windows as one row per field under
column heads and, after the owner's second look, as compact rows with a three-dot menu (ADR-083, addenda 1 and 2)."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import graph_url, kind_of, node, post

DIALOG = "#node-modal"
LONG_NAME = (
    "A long name for an action that does something useful with a card " * 3
)  # 192 characters

BOXES = """(root) => {
  const box = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; };
  const q = (sel) => { const e = root.querySelector(sel); return e ? box(e) : null; };
  return {
    grip: q('.sf__grip'), name: q('.sf__name'), type: q('.sf__type'), required: q('.sf__required .sf__check'),
    description: q('.sf__description'), extra: q('.sf__extra'), more: q('.sf__more'),
  };
}"""

LABEL_WIDTH = """(card) => {
  // the width of the written port labels (drawn by ::after at the card's right edge): measured with a span in the same font
  const out = {};
  for (const port of card.querySelectorAll(':scope > .ge-port[data-label]')) {
    if (port.dataset.side !== 'right') continue;
    const style = getComputedStyle(port, '::after');
    const probe = document.createElement('span');
    probe.style.cssText = `position:absolute;visibility:hidden;white-space:nowrap;font:${style.font}`;
    probe.textContent = port.dataset.label;
    document.body.append(probe);
    const width = probe.getBoundingClientRect().width;
    probe.remove();
    const r = port.getBoundingClientRect();
    if (r.width === 0 || getComputedStyle(port).display === 'none') continue; // a port the node does not show (the error output while it is off)
    out[port.dataset.label] = {left: r.right - 14 - width, width};
  }
  return out;
}"""


def _placed(api: httpx.Client, count: int, name: str) -> dict[str, Any]:
    """A pipeline with `count` placements of one action definition called `name`."""
    definition = post(api, "/api/actions", name=name)
    pipeline = post(api, "/api/pipelines", name=f"Names {count} {len(name)}")
    stage = node(api, pipeline, "stage", name="Stage")
    for i in range(count):
        action = node(api, pipeline, "action", stage_id=stage["id"], x=24 + i * 10, y=48 + i * 90)
        api.patch(
            f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
        ).raise_for_status()
    return pipeline


STILL = """() => new Promise((resolve) => {
  // the dialog opens with a short animation: measure when its box has stood still for a few frames
  const panel = document.querySelector('#node-modal .modal__panel');
  let last = '', same = 0;
  const tick = () => {
    const r = panel.getBoundingClientRect();
    const now = [r.left, r.top, r.width, r.height].map((n) => n.toFixed(1)).join();
    same = now === last ? same + 1 : 0;
    last = now;
    same >= 4 ? resolve(true) : requestAnimationFrame(tick);
  };
  tick();
})"""


def _still(page: Page) -> None:
    page.evaluate(STILL)


def _no_overlap(boxes: dict[str, Any], names: list[str]) -> None:
    present = [(n, boxes[n]) for n in names if boxes[n]]
    for i, (one_name, one) in enumerate(present):
        for other_name, other in present[i + 1 :]:
            apart = (
                one["r"] <= other["l"] + 1
                or other["r"] <= one["l"] + 1
                or one["b"] <= other["t"] + 1
                or other["b"] <= one["t"] + 1
            )
            assert apart, f"{one_name} and {other_name} overlap: {one} {other}"


# ── the name on the card ──────────────────────────────────────────────


def test_a_numbered_placement_shows_its_number_first_and_quiet_and_cuts_a_long_name_before_the_port_labels(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _placed(api, 2, LONG_NAME.strip())
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    cards = page.locator(".ge-node--action")
    expect(cards).to_have_count(2)
    first = cards.first
    name = first.locator(".ge-node__name")
    number = name.locator(".ge-node__number")
    expect(number).to_have_text("#1")
    # the number comes first, then the name
    assert name.inner_text().startswith("#1 A long name")
    # it is quieter than the name: lighter and not larger
    quiet = page.evaluate(
        "(n) => { const a = getComputedStyle(n.querySelector('.ge-node__number')); const b = getComputedStyle(n);"
        " return {weight: Number(a.fontWeight), nameWeight: Number(b.fontWeight), size: parseFloat(a.fontSize), nameSize: parseFloat(b.fontSize)}; }",
        name.element_handle(),
    )
    assert quiet["weight"] < quiet["nameWeight"] and quiet["size"] <= quiet["nameSize"], quiet
    # a name too long for the card is cut with an ellipsis on one line; the whole name is the tooltip
    cut = page.evaluate(
        "(n) => ({overflow: n.scrollWidth > n.clientWidth, ellipsis: getComputedStyle(n).textOverflow, wrap: getComputedStyle(n).whiteSpace})",
        name.element_handle(),
    )
    assert cut == {"overflow": True, "ellipsis": "ellipsis", "wrap": "nowrap"}, cut
    assert (name.get_attribute("title") or "").startswith(LONG_NAME.strip()), name.get_attribute(
        "title"
    )
    # and it never reaches the port labels On Pass / On Error
    labels = first.evaluate(LABEL_WIDTH)
    assert set(labels) >= {"On Pass"}, labels
    right = name.bounding_box()
    assert right
    for label, where in labels.items():
        assert right["x"] + right["width"] <= where["left"] - 2, (label, right, where)


def test_a_card_without_a_number_shows_only_the_name(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _placed(api, 1, "Single check")
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    name = page.locator(".ge-node--action .ge-node__name")
    expect(name).to_have_text("Single check")
    expect(name.locator(".ge-node__number")).to_have_count(0)


def test_the_window_of_a_placement_shows_its_number_quietly_and_a_rename_may_use_the_whole_name(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _placed(api, 2, "Window check")
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    card = page.locator(".ge-node--action").first
    card.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Settings").click()
    title = page.locator(f"{DIALOG} .ge-inspector__heading h2")
    expect(title).to_have_text("#1 Window check")
    expect(title.locator(".ge-inspector__number")).to_have_text("#1")
    page.keyboard.press("Escape")
    # a node the user names: the window edits the whole name, up to the existing limit of 255 characters
    action = post(api, "/api/actions", name="Names of nodes")
    code = node(api, action, "code", name="Long code")
    full = "n" * 255
    api.patch(f"{graph_url(action)}/nodes/{code['id']}", json={"name": full}).raise_for_status()
    refused = api.patch(f"{graph_url(action)}/nodes/{code['id']}", json={"name": "n" * 256})
    assert refused.status_code == 422, "a name of 256 characters is refused"
    assert "255" in refused.text, refused.text
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    heading = page.locator(f"{DIALOG} .ge-inspector__heading h2")
    expect(heading).to_have_text(full)  # the window shows the whole name, the card only cuts it


# ── the field list of Trigger, Output and Complete ────────────────────


def _trigger_inputs(api: httpx.Client) -> dict[str, Any]:
    action = post(api, "/api/actions", name="Rows")
    api.patch(
        f"{graph_url(action)}/nodes/{kind_of(api, action, 'trigger')['id']}",
        json={
            "config": {
                "inputs": [
                    {"name": "who", "type": "text", "required": True, "description": "The person"},
                    {"name": "kind", "type": "choice", "choices": ["a", "b"], "default": "a"},
                ]
            }
        },
    ).raise_for_status()
    return action


def _open_trigger(page: Page, base_url: str, action: dict[str, Any]) -> Locator:
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--trigger").dblclick(position={"x": 20, "y": 5})
    dialog = page.locator(DIALOG)
    expect(dialog.locator(".sf--wide")).to_have_count(1)
    _still(page)
    return dialog


def _stored_inputs(api: httpx.Client, action: dict[str, Any]) -> list[dict[str, Any]]:
    config = kind_of(api, action, "trigger")["config"] or {}
    return list(config.get("inputs", []))


def test_the_trigger_window_is_small_and_each_input_is_one_compact_row_under_column_heads(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _trigger_inputs(api)
    page.set_viewport_size({"width": 1280, "height": 900})
    dialog = _open_trigger(page, base_url, action)
    heads = dialog.locator(".sf__head .sf__h")
    assert heads.all_inner_texts() == ["Name *", "Type", "Required"]
    rows = dialog.locator(".sf__row")
    expect(rows).to_have_count(2)
    panel = dialog.locator(".modal__panel").bounding_box()
    assert panel and panel["width"] <= 640, panel  # the owner's mock: a small window
    head_boxes = {
        part: dialog.locator(f".sf__h--{part}").bounding_box()
        for part in ("name", "type", "required")
    }
    for index in range(2):
        boxes = rows.nth(index).evaluate(BOXES)
        order = ["grip", "name", "type", "required", "more"]
        tops = [boxes[n]["t"] + boxes[n]["h"] / 2 for n in order]
        assert max(tops) - min(tops) <= 8, (index, tops)  # one band
        lefts = [boxes[n]["l"] for n in order]
        assert lefts == sorted(lefts), (index, lefts)
        _no_overlap(boxes, order)
        for part in ("name", "type"):
            head = head_boxes[part]
            assert head and abs(boxes[part]["l"] - head["x"]) <= 2, (part, boxes[part], head)
    # the bin is in the menu: nothing at the end of the row
    expect(dialog.locator(".sf__bin")).to_have_count(0)
    # what a field has is shown, nothing else
    first, second = rows.nth(0), rows.nth(1)
    expect(first.locator(".sf__description")).to_have_value("The person")
    expect(first.locator(".sf__extra")).to_have_count(0)
    expect(second.locator(".sf__description")).to_have_count(0)
    expect(second.locator(".sf__extra")).to_have_value("a")
    # the text for a model is not here, and the description sits on a line of its own under the name
    assert (
        first.locator(".sf__description").get_attribute("placeholder") != "What the model puts here"
    )
    description = first.locator(".sf__description").bounding_box()
    name = first.locator(".sf__name").bounding_box()
    assert description and name
    assert description["y"] >= name["y"] + name["height"] - 1
    assert abs(description["x"] - name["x"]) <= 2
    # the values of a choice are a line of their own under the row
    expect(second.locator(".sf__choices")).to_be_visible()


def test_the_row_menu_adds_and_removes_the_description_and_the_default_and_deletes_the_field(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Menu rows")
    api.patch(
        f"{graph_url(action)}/nodes/{kind_of(api, action, 'trigger')['id']}",
        json={"config": {"inputs": [{"name": "who", "type": "text", "required": False}]}},
    ).raise_for_status()
    page.set_viewport_size({"width": 1280, "height": 900})
    dialog = _open_trigger(page, base_url, action)
    row = dialog.locator(".sf__row").first
    expect(row.locator(".sf__description")).to_have_count(0)
    expect(row.locator(".sf__extra")).to_have_count(
        0
    )  # the window stays small until the menu adds them
    more = row.locator(".sf__more")
    menu = page.get_by_role("menu")
    items = menu.get_by_role("menuitem")

    def open_menu() -> None:
        more.click()
        expect(menu).to_be_visible()

    open_menu()
    assert items.all_inner_texts() == ["Add description", "Add default value", "Delete"]
    items.filter(has_text="Add description").click()
    description = row.locator(".sf__description")
    expect(description).to_be_visible()
    expect(description).to_be_focused()
    description.fill("The person")
    description.press("Enter")
    eventually(lambda: _stored_inputs(api, action)[0].get("description"), "The person")
    open_menu()
    assert items.all_inner_texts() == ["Remove description", "Add default value", "Delete"]
    items.filter(has_text="Add default value").click()
    default = row.locator(".sf__extra")
    expect(default).to_be_focused()
    expect(default).to_have_attribute(
        "placeholder", "Default value"
    )  # it sits on a line of its own: it says what it is
    default.fill("anna")
    default.press("Enter")
    eventually(lambda: _stored_inputs(api, action)[0].get("default"), "anna")
    open_menu()
    items.filter(has_text="Remove default value").click()
    expect(row.locator(".sf__extra")).to_have_count(0)
    eventually(lambda: _stored_inputs(api, action)[0].get("default") or "", "")
    open_menu()
    items.filter(has_text="Remove description").click()
    expect(row.locator(".sf__description")).to_have_count(0)
    eventually(lambda: _stored_inputs(api, action)[0].get("description") or "", "")
    # the keyboard: the menu button opens with Enter, the arrow keys move, Escape closes and gives the focus back
    more.focus()
    page.keyboard.press("Enter")
    expect(menu).to_be_visible()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(more).to_be_focused()
    # Delete is in the menu and removes the field
    open_menu()
    items.filter(has_text="Delete").click()
    expect(dialog.locator(".sf__row")).to_have_count(0)
    eventually(lambda: _stored_inputs(api, action), [])


def test_the_keyboard_goes_through_a_row_in_the_order_of_its_columns(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _trigger_inputs(api)
    dialog = _open_trigger(page, base_url, action)
    first = dialog.locator(".sf__row").first
    first.locator(".sf__name").focus()
    seen = []
    for _ in range(4):
        page.keyboard.press("Tab")
        seen.append(
            page.evaluate(
                "document.activeElement.className.split(' ').find(c => c.startsWith('sf__'))"
            )
        )
    assert seen == ["sf__type", "sf__check", "sf__more", "sf__description"], seen


def test_in_a_narrow_window_the_rows_are_stacked_again_without_overlap(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _trigger_inputs(api)
    page.set_viewport_size({"width": 390, "height": 900})
    dialog = _open_trigger(page, base_url, action)
    expect(dialog.locator(".sf__row").first).to_be_visible()
    expect(dialog.locator(".sf__head")).to_be_hidden()
    boxes = dialog.locator(".sf__row").first.evaluate(BOXES)
    assert boxes["description"]["t"] >= boxes["name"]["b"] - 1, "the description is under the name"
    _no_overlap(boxes, ["grip", "name", "type", "required", "description", "extra", "more"])


def test_the_output_window_has_no_required_column_and_names_the_value_column(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = post(api, "/api/actions", name="Out rows")
    api.patch(
        f"{graph_url(action)}/nodes/{kind_of(api, action, 'output')['id']}",
        json={"config": {"outputs": [{"name": "greeting", "type": "text", "value": "Hello"}]}},
    ).raise_for_status()
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/actions/{action['slug']}")
    page.locator(".ge-node--output").dblclick(position={"x": 30, "y": 5})
    dialog = page.locator(DIALOG)
    expect(dialog.locator(".sf__row").first).to_be_visible()
    _still(page)
    heads: Locator = dialog.locator(".sf__head .sf__h")
    assert heads.all_inner_texts() == ["Name *", "Type", "Value"]
    boxes = dialog.locator(".sf__row").first.evaluate(BOXES)
    _no_overlap(boxes, ["grip", "name", "type", "extra", "more"])
    assert boxes["extra"]["l"] > boxes["type"]["l"], "the value is the last column before the menu"
    # an output always has its value on the row; the menu keeps the description and the deletion
    more = dialog.locator(".sf__more").first
    more.click()
    assert page.get_by_role("menu").get_by_role("menuitem").all_inner_texts() == [
        "Add description",
        "Delete",
    ]


def test_the_required_box_is_the_shared_checkbox_and_toggles_by_key_and_by_its_label(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    action = _trigger_inputs(api)
    page.set_viewport_size({"width": 1280, "height": 900})
    dialog = _open_trigger(page, base_url, action)
    rows = dialog.locator(".sf__row")
    box = rows.nth(0).locator("label.ck input.check.ck__input")
    expect(box).to_have_count(
        1
    )  # the shared component: a label around the native input, not a bare native box
    looks = box.evaluate(
        "e => { const s = getComputedStyle(e); return {appearance: s.appearance, radius: s.borderTopLeftRadius, bg: s.backgroundColor}; }"
    )
    assert looks["appearance"] == "none" and looks["radius"] != "0px", looks
    accent = page.evaluate(
        "() => { const d = document.createElement('div'); d.style.background = 'var(--color-accent)'; document.body.append(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c; }"
    )
    assert looks["bg"] == accent, (
        looks,
        accent,
    )  # checked: filled in the accent colour (purple), the tick is drawn on it
    empty = (
        rows.nth(1).locator("input.sf__check").evaluate("e => getComputedStyle(e).backgroundColor")
    )
    assert empty == "rgba(0, 0, 0, 0)", empty  # unchecked: an empty square with a soft border
    # the keyboard: Space toggles it
    second = rows.nth(1).locator("input.sf__check")
    second.focus()
    page.keyboard.press("Space")
    expect(second).to_be_checked()
    eventually(lambda: _stored_inputs(api, action)[1].get("required"), True)
    # the text of the label is part of the box in the stacked layout: a click on it toggles
    page.set_viewport_size({"width": 390, "height": 900})
    _still(page)
    text = rows.nth(1).locator(".ck__text")
    expect(text).to_be_visible()
    text.click()
    expect(second).not_to_be_checked()
    eventually(lambda: _stored_inputs(api, action)[1].get("required"), False)

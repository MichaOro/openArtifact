"""The guard editor as a form manifest and the attach dialog (ADR-062, ADR-060): the add popup has "New guard…" as the
primary button and "Attach guard…" next to it, the attach dialog is a combobox that narrows as you type and offers only the
guards not attached yet, the editor lays its manifest out in two columns on a wide window and one on a narrow one, folds
the advanced fields, marks what breaks a limit and no longer shows "Can watch" (the data stays)."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_guards import _attach, _guard, _open, _pipeline, _popup, _window

INTERVAL = {"type": "interval", "every_seconds": 60, "for_seconds": 0, "cooldown_seconds": 600}
IDLE = {
    "type": "group",
    "mode": "all",
    "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 900}],
}


def _box(el: Locator) -> dict[str, float]:
    box = el.bounding_box()
    assert box is not None
    return box


def _open_editor(page: Page, base_url: str, guard: dict[str, Any]) -> Locator:
    page.goto(f"{base_url}/guards?open={guard['id']}")
    return _window(page)


# ── the add popup and the attach dialog ──────────────────────────────


def test_the_attach_dialog_narrows_as_you_type_and_offers_only_guards_not_attached_here(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    stage = pipeline["stage"]["id"]
    _guard(api, "Health guard")
    _guard(api, "Health agent", trigger=INTERVAL, when=IDLE)
    _guard(api, "Stall guard", description="Watches the health of a long run")
    _attach(api, _guard(api, "Round guard"), pipeline, "stage", stage)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator("[data-stage-add]").click()
    page.get_by_role("menuitem", name="Guard").click()
    popup = _popup(page)
    expect(popup.get_by_role("button", name="New guard…")).to_have_class(
        re.compile("button--primary")
    )
    popup.get_by_role("button", name="Attach guard…").click()

    dialog = page.locator("#guard-attach-modal")
    expect(dialog.locator(".modal__title")).to_have_text("Attach guard")
    box = dialog.get_by_role("combobox", name="Guard")
    attach = dialog.get_by_role("button", name="Attach", exact=True)
    expect(box).to_be_focused()
    expect(attach).to_be_disabled()  # nothing chosen yet
    names = dialog.locator(".combobox__name")

    box.fill("hea")
    expect(box).to_have_attribute("aria-expanded", "true")
    expect(names).to_have_text(
        ["Health agent", "Health guard", "Stall guard"]
    )  # names first, then "health" in a text
    box.fill("health a")
    expect(names).to_have_text(["Health agent"])
    expect(dialog.locator(".combobox__description").first).to_contain_text("Every 1 minute")
    box.fill("round guard")
    expect(dialog.locator(".combobox__empty")).to_have_text(
        "No guard matches."
    )  # it hangs here already
    box.fill("")
    expect(names).to_have_text(["Health agent", "Health guard", "Stall guard"])

    box.fill("health g")
    page.keyboard.press("ArrowDown")  # the highlight leaves the first option
    page.keyboard.press("ArrowUp")
    expect(box).to_have_attribute("aria-activedescendant", re.compile("combobox-.*-option-0"))
    page.keyboard.press("Enter")  # takes it, the form is not submitted
    expect(box).to_have_value("Health guard")
    expect(box).to_have_attribute("aria-expanded", "false")
    expect(dialog).to_be_visible()
    expect(attach).to_be_enabled()
    box.fill("Health")  # typing again clears the choice
    expect(attach).to_be_disabled()
    box.fill("")
    page.keyboard.press("ArrowDown")
    expect(names.first).to_be_visible()
    page.keyboard.press("Escape")  # the list only
    expect(dialog.locator(".combobox__list")).to_be_hidden()
    expect(dialog).to_be_visible()

    box.fill("health a")
    page.keyboard.press("Enter")
    attach.click()
    expect(dialog).to_be_hidden()
    popup = _popup(page)  # back in the popup, now with the guard under "Attached here"
    expect(popup.locator(".gd-attached__name")).to_have_text(["Health agent", "Round guard"])
    expect(page.locator(".ge-stage__header [data-guard-shield]")).to_have_attribute(
        "title", "2 guards configured"
    )
    [place] = [a for a in api.get("/api/guard-attachments").json() if a["name"] == "Health agent"]
    assert (place["scope_type"], place["scope_id"]) == ("stage", stage)


def test_a_guard_is_offered_to_the_attach_dialog_only_while_it_hangs_nowhere_on_that_scope(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    guard = _guard(api, "Only one")
    _attach(api, guard, pipeline, "pipeline", pipeline["id"])
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    page.locator("[data-stage-add]").click()
    page.get_by_role("menuitem", name="Guard").click()
    popup = _popup(page)  # on the stage it is still free ...
    expect(popup.get_by_role("button", name="Attach guard…")).not_to_have_attribute(
        "aria-disabled", "true"
    )
    popup.get_by_role("button", name="Attach guard…").click()
    dialog = page.locator("#guard-attach-modal")
    dialog.get_by_role("combobox", name="Guard").fill("only")
    expect(dialog.locator(".combobox__name")).to_have_text(["Only one"])
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    page.keyboard.press("Escape")
    # ... and from the pipeline's own popup it is attached, so there is nothing to attach
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    page.locator("[data-placeholder=guard]").click()
    popup = _popup(page)
    expect(popup.get_by_role("button", name="Attach guard…")).to_have_attribute(
        "aria-disabled", "true"
    )
    expect(popup).to_contain_text("No other guard to attach.")


# ── the guard editor drawn from its manifest ─────────────────────────


def test_the_guard_editor_has_two_columns_on_a_wide_window_one_on_a_narrow_one_and_is_no_endless_column(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _guard(api, "Stall guard", trigger=INTERVAL, when=IDLE)
    page.set_viewport_size({"width": 1280, "height": 800})
    window = _open_editor(page, base_url, guard)
    trigger, then = (window.locator(f"[data-section={k}]") for k in ("trigger", "then"))
    condition = window.locator("[data-section=condition]")
    escalation, logic = (window.locator(f"[data-section={k}]") for k in ("escalation", "logic"))
    t, th, c = _box(trigger), _box(then), _box(condition)
    assert t["x"] < th["x"] and abs(t["y"] - th["y"]) < 2, "trigger and consequence side by side"
    assert c["width"] > t["width"] * 1.8, "the rule builder has the whole width"
    e, lg = _box(escalation), _box(logic)
    assert e["x"] < lg["x"] and abs(e["y"] - lg["y"]) < 2
    panel = _box(window.locator(".modal__panel"))
    assert panel["width"] < 900, f"content-sized, not the 64 rem cap: {panel['width']:.0f} px"
    assert panel["height"] <= 800 - 32, (
        f"fits the window without an endless scroll: {panel['height']:.0f} px"
    )
    assert window.evaluate("el => el.scrollHeight <= el.clientHeight + 1"), (
        "the overlay does not scroll"
    )
    row = window.locator(".rb-row")  # a condition at this width stays on one line
    assert row.evaluate(
        """el => {
            const middles = [...el.children].map(c => { const r = c.getBoundingClientRect(); return r.top + r.height / 2; });
            return Math.max(...middles) - Math.min(...middles) < 3;
        }"""
    )

    page.set_viewport_size({"width": 360, "height": 700})
    page.wait_for_timeout(100)
    t, th = _box(trigger), _box(then)
    assert abs(t["x"] - th["x"]) < 2 and th["y"] > t["y"] + t["height"] - 1, (
        "one column below the breakpoint"
    )
    assert window.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), (
        "no horizontal scrolling at 360 px"
    )


def test_the_advanced_fields_are_folded_until_asked_for_and_an_edit_of_one_is_saved(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _guard(api, "Stall guard", trigger=INTERVAL, when=IDLE)
    window = _open_editor(page, base_url, guard)
    held = window.get_by_label("Held for (seconds)")
    expect(window.get_by_label("Check every (seconds)")).to_have_value("60")
    expect(held).to_have_count(0)  # advanced: folded
    more = window.get_by_role("button", name="More options")
    expect(more).to_have_attribute("aria-expanded", "false")
    more.click()
    expect(held).to_have_value("0")
    expect(window.get_by_label("Quiet after firing (seconds)")).to_have_value("600")
    expect(window.get_by_role("button", name="Fewer options")).to_have_attribute(
        "aria-expanded", "true"
    )
    held.fill("30")
    window.locator("[data-submit]").click()
    expect(window).to_be_hidden()
    stored = api.get(f"/api/guards/{guard['id']}").json()
    assert stored["trigger"] == {**INTERVAL, "for_seconds": 30}
    window = _open_editor(page, base_url, guard)
    expect(window.get_by_label("Held for (seconds)")).to_have_count(
        0
    )  # folded again on every opening
    window.get_by_role("button", name="Cancel").click()


def test_the_trigger_kind_decides_which_fields_are_there_and_a_missing_event_is_marked_at_its_field(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _guard(api, "Loop watch")  # an event trigger: entered
    window = _open_editor(page, base_url, guard)
    events = window.locator("[data-section=trigger] .rb-chip")
    expect(events).to_have_count(5)
    expect(window.get_by_label("Check every (seconds)")).to_have_count(0)
    window.get_by_role("button", name="Every few seconds").click()
    expect(events).to_have_count(0)
    expect(window.get_by_label("Check every (seconds)")).to_have_value("60")  # the kind's defaults
    window.get_by_role("button", name="On an event").click()
    expect(events).to_have_count(5)
    for chip in events.all():  # none chosen: the field says so and nothing is saved
        if chip.locator("input").is_checked():
            chip.click()
    window.locator("[data-submit]").click()
    expect(window.locator("[data-error-for='trigger.events']")).to_have_text("Fill this in")
    expect(window.locator("[data-form-error]")).to_have_text("Choose at least one event.")
    assert api.get(f"/api/guards/{guard['id']}").json()["trigger"]["events"] == ["enter"]
    window.get_by_role("checkbox", name="Left").check()
    window.get_by_role("button", name="Every few seconds").click()
    window.locator("[data-submit]").click()
    expect(window).to_be_hidden()
    assert api.get(f"/api/guards/{guard['id']}").json()["trigger"] == {
        "type": "interval",
        "every_seconds": 60,
        "for_seconds": 0,
        "cooldown_seconds": 0,
    }


def test_can_watch_is_hidden_but_what_a_guard_may_watch_is_kept(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    guard = _guard(api, "Stage only", scope_types=["stage"])
    window = _open_editor(page, base_url, guard)
    expect(window).not_to_contain_text("Can watch")
    expect(window.locator("[data-guard-scopes]")).to_have_count(0)
    window.locator("[data-submit]").click()
    expect(window).to_be_hidden()
    assert api.get(f"/api/guards/{guard['id']}").json()["scope_types"] == [
        "stage"
    ]  # saved with what it had
    page.goto(f"{base_url}/guards")
    page.get_by_role("button", name="New guard").click()
    page.get_by_role("menuitem", name="Blank guard").click()
    window = _window(page)
    window.get_by_role("textbox", name="Guard name").fill(
        "Fresh"
    )  # a new guard starts with the title as its field
    page.keyboard.press("Enter")
    window.get_by_role("button", name="Add condition").click()
    window.locator("[data-submit]").click()
    expect(window).to_be_hidden()
    created = next(g for g in api.get("/api/guards").json() if g["name"] == "Fresh")
    assert created["scope_types"] == [
        "pipeline",
        "stage",
        "action",
    ]  # a new guard may watch all three


def test_the_guard_form_speaks_german(page: Page, base_url: str, api: httpx.Client) -> None:
    guard = _guard(api, "Loop watch")
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    window = _open_editor(page, base_url, guard)
    expect(window.locator("[data-section=trigger] .fv-section__title")).to_contain_text("Auslöser")
    expect(window.locator("[data-section=then] .fv-section__title")).to_contain_text("Dann")
    expect(window.get_by_role("button", name="Bei einem Ereignis")).to_be_visible()
    expect(window.get_by_role("checkbox", name="Betreten (jede Runde)")).to_be_checked()
    window.get_by_role("button", name="In einem Intervall").click()
    expect(window.get_by_role("button", name="Weitere Optionen")).to_be_visible()

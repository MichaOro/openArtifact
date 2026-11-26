"""Areas in the arrange mode of the manifest windows (ADR-063 addendum): a setting moves between Definition, Behaviour and
areas of the user's own by pointer and by key, in a wide window and in a narrow one where the areas are stacked; the user
adds an area, names it in place and deletes it while it is empty; shipped areas stay; the saved placement reaches the normal
view and the next window of the kind; the same for a form (the guard editor)."""

from __future__ import annotations

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import add_setting, drag
from tests.e2e.test_window_layout import (
    GUARD,
    _guard_window,
    _item,
    _menu,
    _node_window,
    _reset,
    _settled,
)

AGENT = "/api/ui-layouts/nodes/agent"


def _arrange(page: Page, window: Locator) -> Locator:
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    expect(arrange).to_be_visible()
    return arrange


def _grip(arrange: Locator, area: str, field: str) -> Locator:
    return arrange.locator(f"[data-section='{area}'] [data-field='{field}'] .lw-grip")


def _fields(arrange: Locator, area: str) -> list[str]:
    return [
        el.get_attribute("data-field") or ""
        for el in arrange.locator(f"[data-section='{area}'] .lw-field").all()
    ]


def _save(page: Page, window: Locator) -> None:
    _item(_menu(page, window), "Save layout").click()
    expect(window.locator(".lw-arrange")).to_have_count(0)


def _where(window: Locator, key: str) -> str:
    """The area a setting is drawn in, in the normal view of a node's window."""
    column = window.locator(
        f".ge-settings__column:has([data-setting='{key}'], [data-focus-key='setting-{key}'])"
    )
    expect(column).to_have_count(1)
    return column.get_attribute("data-section") or ""


# ── a setting in any area ─────────────────────────────────────────────


def test_a_setting_is_dragged_into_the_other_area_and_the_node_window_follows(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    window_name = "/api/ui-layouts/nodes/http"
    _reset(api, window_name)
    window = _node_window(page, base_url, api, "http")
    add_setting(
        page, "If the node fails"
    )  # optional: drawn once added, in the area the layout puts it in
    assert _where(window, "url") == "definition" and _where(window, "on_failure") == "behaviour"
    arrange = _arrange(page, window)
    drag(
        page,
        _grip(arrange, "definition", "url"),
        arrange.locator("[data-section='behaviour'] .lw-fields").first,
    )
    expect(arrange.locator("[data-section='behaviour'] [data-field='url']")).to_have_count(1)
    drag(
        page,
        _grip(arrange, "behaviour", "on_failure"),
        arrange.locator("[data-section='definition'] .lw-fields").first,
    )
    expect(arrange.locator("[data-section='definition'] [data-field='on_failure']")).to_have_count(
        1
    )
    expect(window.locator("[data-layout-handle]")).to_have_attribute("data-dirty", "")
    _save(page, window)
    saved = api.get(window_name).json()
    assert saved["customised"] is True
    by = {s["key"]: s["fields"] for s in saved["layout"]["sections"]}
    assert "url" in by["behaviour"] and "on_failure" in by["definition"]
    # the window of the node draws them where they were put: the setting keeps its control, only its place changed
    assert _where(window, "url") == "behaviour"
    assert _where(window, "on_failure") == "definition"
    # a second node of the kind has the same placement
    page.keyboard.press("Escape")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "http")
    page.click("[data-add=http]")
    page.locator(".ge-node--http").last.dblclick(position={"x": 30, "y": 5})
    second = page.locator("#node-modal")
    assert _where(second, "url") == "behaviour"
    _reset(api, window_name)


def test_a_setting_moves_into_the_next_area_by_key_and_the_move_is_announced(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, AGENT)
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    _grip(arrange, "definition", "user_prompt").focus()
    page.keyboard.press(
        "ArrowDown"
    )  # the last setting of Definition: on into Behaviour, at its start
    expect(arrange.locator("[data-section='behaviour'] .lw-field").first).to_have_attribute(
        "data-field", "user_prompt"
    )
    expect(page.locator(".lw-arrange [role='status']")).to_contain_text("Behaviour")
    assert (
        page.evaluate("() => document.activeElement.dataset.gripKey") == "f:behaviour:user_prompt"
    )
    page.keyboard.press("Alt+ArrowLeft")  # back to the area before, at the same position
    expect(arrange.locator("[data-section='definition'] [data-field='user_prompt']")).to_have_count(
        1
    )
    page.keyboard.press("ArrowRight")
    expect(arrange.locator("[data-section='behaviour'] [data-field='user_prompt']")).to_have_count(
        1
    )
    assert (
        page.evaluate("() => document.activeElement.dataset.gripKey") == "f:behaviour:user_prompt"
    )
    _item(_menu(page, window), "Discard changes").click()


def test_the_fixed_block_of_the_agent_cannot_be_arranged(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, AGENT)
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    fixed = arrange.locator(".lw-fixed")
    expect(fixed).to_have_count(1)
    assert fixed.locator(".lw-grip").count() == 0  # no grip: nothing to drag
    refused = api.put(AGENT, json={"sections": [{"key": "behaviour", "fields": ["agent_id"]}]})
    assert refused.status_code == 422 and "stays where it is" in refused.json()["detail"]
    _item(_menu(page, window), "Discard changes").click()


# ── a narrow window: the areas are stacked ────────────────────────────


def test_in_a_narrow_window_the_areas_are_stacked_and_a_setting_still_moves_between_them(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, AGENT)
    page.set_viewport_size({"width": 700, "height": 900})
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    definition = _settled(page, arrange.locator("[data-section='definition']"))
    behaviour = _settled(page, arrange.locator("[data-section='behaviour']"))
    assert abs(definition["x"] - behaviour["x"]) < 4  # one column
    assert behaviour["y"] > definition["y"] + definition["height"] - 4  # Behaviour under Definition
    drag(
        page,
        _grip(arrange, "definition", "system_prompt"),
        arrange.locator("[data-section='behaviour'] .lw-fields").first,
    )
    expect(
        arrange.locator("[data-section='behaviour'] [data-field='system_prompt']")
    ).to_have_count(1)
    drag(
        page,
        _grip(arrange, "behaviour", "system_prompt"),
        arrange.locator("[data-section='definition'] .lw-fields").first,
    )
    expect(
        arrange.locator("[data-section='definition'] [data-field='system_prompt']")
    ).to_have_count(1)
    _grip(arrange, "definition", "user_prompt").focus()
    page.keyboard.press("Alt+ArrowDown")  # by key it crosses into the area below
    expect(arrange.locator("[data-section='behaviour'] [data-field='user_prompt']")).to_have_count(
        1
    )
    # an area is dragged under the other in the stack
    drag(
        page,
        arrange.locator("[data-section='definition'] .lw-section__head .lw-grip"),
        arrange.locator("[data-section='behaviour'] .lw-fields").first.locator(
            "xpath=following::*[1]"
        ),
    )
    _item(_menu(page, window), "Discard changes").click()


def test_the_settings_an_agent_supplies_follow_the_placement_of_their_rows(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The Agent node's prompts are override rows of the chosen agent: they sit where the layout puts them like any setting."""
    _reset(api, AGENT)
    agent = api.post(
        "/api/agents",
        json={
            "name": "Layout agent",
            "draft": {"system_prompt": "You help.", "user_prompt": "Say hi."},
        },
    ).json()
    assert api.post(f"/api/agents/{agent['id']}/publish").status_code == 200
    saved = api.get(AGENT).json()["shipped"]
    saved["sections"][0]["fields"].remove("user_prompt")
    saved["sections"][1]["fields"].insert(0, "user_prompt")
    assert api.put(AGENT, json=saved).status_code == 200
    window = _node_window(page, base_url, api, "agent")
    window.locator("select[data-focus-key='agent-agent_id']").select_option(label="Layout agent")
    add_setting(
        page, "User prompt"
    )  # the prompts are drawn once the node overrides them (added here)
    add_setting(page, "System prompt")
    row = window.locator("[data-setting='user_prompt']")
    expect(row).to_have_count(1)
    expect(
        window.locator(
            ".ge-settings__column[data-section='behaviour'] [data-setting='user_prompt']"
        )
    ).to_have_count(1)
    expect(
        window.locator(
            ".ge-settings__column[data-section='definition'] [data-setting='system_prompt']"
        )
    ).to_have_count(1)
    _reset(api, AGENT)


# ── areas of one's own ────────────────────────────────────────────────


def test_an_area_of_ones_own_is_added_named_filled_deleted_and_saved(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, AGENT)
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    # the shipped areas have no delete button and no rename
    assert arrange.locator("[data-section='definition'] [data-delete-area]").count() == 0
    assert arrange.locator("[data-section='behaviour'] .inline-name").count() == 0
    arrange.locator("[data-add-area]").click()
    custom = arrange.locator("[data-custom='true']")
    expect(custom).to_have_count(1)
    expect(custom.get_by_role("textbox", name="Area title")).to_have_value(
        "New area"
    )  # the title is the first thing to give
    page.keyboard.press("Control+a")
    page.keyboard.type("Quick")
    page.keyboard.press("Enter")
    expect(custom.locator("[data-area-title]")).to_have_text("Quick")
    expect(custom.locator(".lw-hint")).to_have_text(
        "Drop settings here"
    )  # empty: it says where to drop
    key = custom.get_attribute("data-section") or ""
    # with a third area the first two stay side by side in a wide window; the new one wraps into the next row
    left = _settled(page, arrange.locator("[data-section='definition']"))
    right = _settled(page, arrange.locator("[data-section='behaviour']"))
    own = _settled(page, custom)
    assert right["x"] > left["x"] + left["width"] - 4 and abs(right["y"] - left["y"]) < 4
    assert own["y"] > left["y"] + 20
    drag(page, _grip(arrange, "behaviour", "on_failure"), custom.locator(".lw-fields").first)
    expect(custom.locator("[data-field='on_failure']")).to_have_count(1)
    delete = custom.locator("[data-delete-area]")
    expect(delete).to_have_attribute("aria-disabled", "true")  # it holds something
    expect(delete).to_have_attribute("title", "Move its settings out first")
    delete.click(force=True)
    expect(custom).to_have_count(1)  # nothing happened
    _save(page, window)
    saved = api.get(AGENT).json()["layout"]["sections"]
    assert [s["key"] for s in saved][-1] == key
    assert saved[-1]["title"] == "Quick" and saved[-1]["fields"] == ["on_failure"]
    # the normal view draws the area with its title and, once the optional setting is added, the setting in it
    add_setting(page, "If the node fails")
    assert _where(window, "on_failure") == key
    expect(
        window.locator(f".ge-settings__column[data-section='{key}'] .ge-settings__title")
    ).to_have_text("Quick")
    # arrange again: take the setting out and delete the empty area
    arrange = _arrange(page, window)
    custom = arrange.locator(f"[data-section='{key}']")
    _grip(arrange, key, "on_failure").focus()
    page.keyboard.press("ArrowLeft")  # into the area before
    expect(arrange.locator("[data-section='behaviour'] [data-field='on_failure']")).to_have_count(1)
    custom.locator("[data-delete-area]").click()
    expect(arrange.locator("[data-custom='true']")).to_have_count(0)
    _save(page, window)
    assert api.get(AGENT).json()["layout"]["sections"][-1]["key"] in ("behaviour", "definition")
    _reset(api, AGENT)


def test_an_empty_area_of_ones_own_is_kept_for_the_arrange_view_and_not_drawn(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, AGENT)
    saved = api.get(AGENT).json()["shipped"]
    saved["sections"].append({"key": "custom_spare", "title": "Spare", "fields": []})
    assert api.put(AGENT, json=saved).status_code == 200
    window = _node_window(page, base_url, api, "agent")
    expect(window.locator(".ge-settings__column[data-section='custom_spare']")).to_have_count(0)
    arrange = _arrange(page, window)
    expect(arrange.locator("[data-section='custom_spare'] [data-area-title]")).to_have_text("Spare")
    _item(_menu(page, window), "Discard changes").click()
    _reset(api, AGENT)


def test_at_most_twelve_areas_of_ones_own(page: Page, base_url: str, api: httpx.Client) -> None:
    _reset(api, AGENT)
    saved = api.get(AGENT).json()["shipped"]
    saved["sections"] += [
        {"key": f"custom_{i}", "title": f"Area {i}", "fields": []} for i in range(12)
    ]
    assert api.put(AGENT, json=saved).status_code == 200
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    add = arrange.locator("[data-add-area]")
    expect(add).to_have_attribute("aria-disabled", "true")
    expect(add).to_have_attribute("title", "At most 12 areas of your own")
    add.click(force=True)  # it says why it is off and does nothing
    expect(arrange.locator("[data-custom='true']")).to_have_count(12)
    saved["sections"].append({"key": "custom_13", "title": "No", "fields": []})
    assert api.put(AGENT, json=saved).status_code == 422
    _item(_menu(page, window), "Discard changes").click()
    _reset(api, AGENT)


def test_the_layout_menu_reset_takes_the_placement_and_the_areas_away(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    http = "/api/ui-layouts/nodes/http"
    saved = api.get(http).json()["shipped"]
    saved["sections"][0]["fields"].remove("url")
    saved["sections"].append({"key": "custom_r1", "title": "Mine", "fields": ["url"]})
    assert api.put(http, json=saved).status_code == 200
    window = _node_window(page, base_url, api, "http")
    assert _where(window, "url") == "custom_r1"
    menu = _menu(page, window)
    _item(menu, "Reset to default").click()
    page.locator("#confirm-modal [data-confirm]").click()
    expect(page.locator("#confirm-modal")).to_be_hidden()
    assert api.get(http).json()["customised"] is False
    window = _node_window(page, base_url, api, "http")
    assert _where(window, "url") == "definition"


# ── a form: the guard editor ──────────────────────────────────────────


def test_a_field_of_the_guard_editor_moves_into_a_section_of_its_own(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _reset(api, GUARD)
    page.set_viewport_size(
        {"width": 1280, "height": 1200}
    )  # the whole arrange view in sight: a drag near the edge would scroll
    window = _guard_window(page, base_url, api)
    arrange = _arrange(page, window)
    arrange.locator("[data-add-area]").click()
    custom = arrange.locator("[data-custom='true']")
    expect(custom.get_by_role("textbox", name="Area title")).to_be_visible()
    page.keyboard.press("Control+a")
    page.keyboard.type("My part")
    page.keyboard.press("Enter")
    expect(custom.locator("[data-area-title]")).to_have_text("My part")
    _settled(
        page, custom
    )  # the view is drawn again after the rename: drag only once it stands still
    drag(
        page,
        arrange.locator("[data-section='then'] [data-field='consequence'] .lw-grip"),
        custom.locator(".lw-fields").first,
    )
    expect(custom.locator("[data-field='consequence']")).to_have_count(1)
    _save(page, window)
    saved = api.get(GUARD).json()["layout"]["sections"]
    mine = next(s for s in saved if s.get("title") == "My part")
    assert mine["fields"] == ["consequence"], saved
    key = mine["key"]
    form = window.locator("[data-form='guard']")
    section = form.locator(f"[data-section='{key}']")
    expect(section).to_be_visible()
    expect(section).to_contain_text("My part")
    expect(
        section.locator("[name='consequence'], [data-field='consequence'], select").first
    ).to_be_visible()
    # the section that lost its only field is not drawn any more
    assert form.locator("[data-section='then']").count() in (0, 1)
    _reset(api, GUARD)


# ── German ────────────────────────────────────────────────────────────


def test_the_area_controls_speak_german(page: Page, base_url: str, api: httpx.Client) -> None:
    _reset(api, AGENT)
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange_de(page, window)
    add = arrange.locator("[data-add-area]")
    expect(add).to_contain_text("Bereich hinzufügen")
    add.click()
    custom = arrange.locator("[data-custom='true']")
    expect(custom.get_by_role("textbox", name="Titel des Bereichs")).to_have_value("Neuer Bereich")
    page.keyboard.press("Escape")
    expect(custom.locator("[data-area-title]")).to_have_text("Neuer Bereich")
    expect(custom.locator(".lw-hint")).to_have_text("Einstellungen hierher ziehen")
    expect(custom.locator("[data-delete-area]")).to_have_attribute(
        "aria-label", "Bereich Neuer Bereich löschen"
    )


def _arrange_de(page: Page, window: Locator) -> Locator:
    _item(_menu(page, window), "Layout bearbeiten").click()
    arrange = window.locator(".lw-arrange")
    expect(arrange).to_be_visible()
    return arrange


# ── both themes ───────────────────────────────────────────────────────


def test_the_area_controls_are_readable_in_both_themes(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    from tests.e2e.test_ui_catalog import TEXT_MIN, _measure, _theme

    _reset(api, AGENT)
    window = _node_window(page, base_url, api, "agent")
    arrange = _arrange(page, window)
    arrange.locator("[data-add-area]").click()
    page.keyboard.press("Enter")
    custom = arrange.locator("[data-custom='true']")
    for theme in ("light", "dark"):
        _theme(page, theme)
        page.wait_for_timeout(300)
        assert _measure(page, arrange.locator("[data-add-area]"))["text"] >= TEXT_MIN, (
            f"add tile / {theme}"
        )
        assert _measure(page, custom.locator(".lw-hint"))["text"] >= TEXT_MIN, f"hint / {theme}"
        assert _measure(page, custom.locator("[data-area-title]"))["text"] >= TEXT_MIN, (
            f"title / {theme}"
        )
        assert _measure(page, custom.locator("[data-delete-area]"))["border"] >= 1.0, (
            f"delete / {theme}"
        )
    _item(_menu(page, window), "Discard changes").click()

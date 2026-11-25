"""The canonical settings dialog of a node (ADR-053): Definition and Behaviour columns, optional settings added on request,
advanced settings folded, and nothing drawn for what a kind does not have."""

from __future__ import annotations

import re
from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import add_setting, eventually, pick_node, tip_of
from tests.helpers import graph_url


def _open(page: Page, base_url: str, api: httpx.Client, kind: str) -> Any:
    definition = api.post("/api/actions", json={"name": "Settings"}).json()
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    pick_node(page, kind)
    page.locator(f".ge-node--{kind}").dblclick(position={"x": 30, "y": 5})
    expect(page.locator("#node-modal")).to_be_visible()
    return definition


def _config(api: httpx.Client, definition: Any, kind: str) -> dict[str, Any]:
    nodes = api.get(graph_url(definition)).json()["nodes"]
    return next(n["config"] for n in nodes if n["kind"] == kind)  # type: ignore[no-any-return]


def test_a_node_with_a_definition_and_a_behaviour_gets_two_columns(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    settings = dialog.locator(".ge-settings")
    expect(settings).to_have_attribute("data-columns", "2")
    expect(dialog).to_have_class(re.compile(r"is-wide"))
    definition = settings.locator('.ge-settings__column[data-section="definition"]')
    behaviour = settings.locator('.ge-settings__column[data-section="behaviour"]')
    for label in ("Method", "URL", "Headers", "Body"):
        expect(definition.get_by_label(label, exact=True)).to_be_visible()
    expect(behaviour.get_by_label("If the node fails", exact=True)).to_have_count(
        0
    )  # the shared failure setting is optional: offered through Add setting, then in Behaviour
    add_setting(page, "If the node fails")
    expect(behaviour.get_by_label("If the node fails", exact=True)).to_be_visible()
    expect(behaviour.get_by_label("Timeout (seconds)", exact=True)).to_have_count(
        0
    )  # optional: not shown yet
    expect(settings.locator(".ge-settings__title")).to_have_text(["Definition", "Behaviour"])
    d, b = definition.bounding_box(), behaviour.bounding_box()
    assert (
        d and b and abs(d["y"] - b["y"]) < 2 and b["x"] > d["x"] + d["width"] - 2
    )  # side by side, same top


def test_the_columns_stack_when_the_dialog_is_narrow(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.set_viewport_size({"width": 700, "height": 900})
    _open(page, base_url, api, "http")
    settings = page.locator("#node-modal .ge-settings")
    d = settings.locator('.ge-settings__column[data-section="definition"]').bounding_box()
    b = settings.locator('.ge-settings__column[data-section="behaviour"]').bounding_box()
    assert d and b and b["y"] >= d["y"] + d["height"] - 2  # Behaviour below Definition
    assert page.evaluate("document.documentElement.scrollWidth") <= 700  # nothing scrolls sideways


def test_a_node_without_behaviour_has_one_column_and_no_empty_section(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "if")
    settings = page.locator("#node-modal .ge-settings")
    expect(settings).to_have_attribute("data-columns", "1")
    expect(settings.locator(".ge-settings__column")).to_have_count(1)
    expect(settings.locator(".ge-settings__title")).to_have_count(
        0
    )  # no headings for a single column
    expect(page.locator("#node-modal")).not_to_have_class(re.compile(r"is-wide"))
    expect(settings.get_by_text("Add setting")).to_have_count(0)  # nothing optional, no empty menu


def test_an_optional_setting_is_added_kept_and_taken_away(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    add_setting(page, "Timeout (seconds) · default 30")  # the menu says what applies meanwhile
    timeout = dialog.get_by_label("Timeout (seconds)", exact=True)
    expect(timeout).to_have_attribute("placeholder", "30")  # the default shows grey
    expect(timeout).to_have_value("")
    timeout.fill("12")
    timeout.press("Enter")
    eventually(lambda: _config(api, definition, "http")["timeout_seconds"], 12)
    # "If the node fails" is optional too: both are set before nothing is left to add
    add_setting(page, "If the node fails")
    dialog.get_by_label("If the node fails", exact=True).select_option(label="Continue")
    eventually(lambda: _config(api, definition, "http")["on_failure"], "continue")

    page.keyboard.press("Escape")  # reopened: a configured optional setting is there without asking
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_value("12")
    expect(dialog.get_by_role("button", name="Add setting")).to_have_count(0)  # nothing left to add

    dialog.get_by_role(
        "button", name="Use the default again: Timeout (seconds)"
    ).click()  # not set again, the default applies
    eventually(lambda: _config(api, definition, "http")["timeout_seconds"], 30)
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_count(0)
    add_setting(page, "Timeout (seconds)")  # offered again

    page.keyboard.press("Escape")  # added but never given a value: not kept
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_count(0)


def test_advanced_settings_are_folded_and_open_while_one_is_set(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "http")
    dialog = page.locator("#node-modal")
    advanced = dialog.locator('.ge-advanced[data-section="behaviour"]')
    expect(advanced).not_to_have_attribute(
        "open", ""
    )  # closed: the accepted status codes are advanced
    expect(dialog.get_by_label("Success status")).to_be_hidden()
    advanced.locator("summary").click()
    status = dialog.get_by_label("Success status")
    status.fill("200, 404")
    status.press("Enter")
    eventually(lambda: _config(api, definition, "http")["success_status"], "200, 404")

    page.keyboard.press("Escape")
    page.locator(".ge-node--http").dblclick(position={"x": 30, "y": 5})
    expect(dialog.locator('.ge-advanced[data-section="behaviour"]')).to_have_attribute(
        "open", ""
    )  # a set value is never hidden
    expect(dialog.get_by_label("Success status")).to_have_value("200, 404")


def test_a_code_node_keeps_its_secrets_in_advanced_and_its_timeout_optional(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "code")
    dialog = page.locator("#node-modal")
    expect(dialog.locator('.ge-advanced[data-section="definition"] summary')).to_have_text(
        "Advanced"
    )
    expect(dialog.get_by_label("Secrets")).to_be_hidden()
    expect(dialog.get_by_role("button", name="Add setting")).to_have_count(1)
    add_setting(
        page, "If the node fails"
    )  # optional like every other node: Stop the run until it is set
    expect(
        dialog.locator(".ge-settings__column[data-section=behaviour]").get_by_label(
            "If the node fails", exact=True
        )
    ).to_be_visible()


def test_a_timer_has_a_single_column_with_its_one_setting(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "timer")
    settings = page.locator("#node-modal .ge-settings")
    expect(settings).to_have_attribute("data-columns", "1")
    expect(settings.get_by_label("Seconds")).to_be_visible()


def test_the_explanation_of_a_field_is_a_tooltip_after_its_label(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "postgres")
    dialog = page.locator("#node-modal")
    query = dialog.get_by_label("Query", exact=True)
    tip = tip_of(dialog, "Query")
    expect(tip).to_be_visible()
    text = "One SQL statement"
    expect(dialog.get_by_text(text)).to_be_hidden()  # not printed under the field
    tip.hover()  # hover opens it
    tooltip = page.get_by_role("tooltip").filter(has_text=text)
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text(
        "Stored in plain text, so no passwords."
    )  # warnings are help too
    box, tip_box = tooltip.bounding_box(), tip.bounding_box()
    assert (
        box and tip_box and box["y"] >= tip_box["y"]
    )  # below the (i), inside the dialog (not hidden behind it)
    page.mouse.move(5, 5)
    expect(tooltip).to_be_hidden()  # leaving closes it
    tip.focus()  # so does keyboard focus open it
    expect(tooltip).to_be_visible()
    page.keyboard.press("Escape")  # Escape closes the tooltip first, the dialog stays
    expect(tooltip).to_be_hidden()
    expect(dialog).to_be_visible()
    described = query.get_attribute("aria-describedby") or ""
    assert (tip.get_attribute("data-tip-id") or "x") in described  # the field is described by it
    expect(
        dialog.get_by_text("0 lines").first
    ).to_be_visible()  # the count stays, on the label's line


def test_the_footer_has_only_the_actions_that_apply_to_the_node(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _open(page, base_url, api, "postgres")
    # nothing to create or open: Delete shares its line with Add guard (a postgres node can be watched)
    expect(page.locator("#node-modal .ge-footer .button")).to_have_text(["Add guard", "Delete"])
    expect(page.locator("#node-modal .ge-actionbar")).to_have_count(0)


def test_the_github_dialog_pairs_resource_and_operation_and_draws_only_what_the_operation_uses(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "github")
    dialog = page.locator("#node-modal")
    resource, operation = dialog.get_by_label("Resource"), dialog.get_by_label("Operation")
    pair = dialog.locator(".ge-settings__pair")
    expect(pair).to_have_count(1)
    r, o = resource.bounding_box(), operation.bounding_box()
    assert r and o and abs(r["y"] - o["y"]) < 2 and o["x"] > r["x"], "side by side on one line"
    # Get repository needs only the repository: nothing about issues, files or comments
    for label in ("Number", "File path", "Comment", "State", "Limit"):
        expect(dialog.get_by_label(label, exact=True)).to_have_count(0)
    # what is not built yet is shown greyed and cannot be chosen
    expect(resource.locator("option", has_text="Release")).to_be_disabled()
    expect(operation.locator("option", has_text="Get license")).to_be_disabled()
    # choosing a resource moves the operation to one that fits, and draws that operation's settings
    resource.select_option("Issue")
    expect(operation).to_have_value("Get issue")
    expect(dialog.get_by_label("Number", exact=True)).to_be_visible()
    eventually(
        lambda: {k: _config(api, definition, "github").get(k) for k in ("resource", "operation")},
        {"resource": "Issue", "operation": "Get issue"},
    )
    resource.select_option("File")
    expect(operation).to_have_value("Get file")
    expect(dialog.get_by_label("File path", exact=True)).to_be_visible()
    expect(dialog.get_by_label("Number", exact=True)).to_have_count(0)
    # the branch is an optional setting: offered through Add setting, not drawn until then
    expect(dialog.get_by_label("Git reference", exact=True)).to_have_count(0)
    add_setting(page, "Git reference")
    expect(dialog.get_by_label("Git reference", exact=True)).to_be_visible()


def test_the_github_mcp_node_has_the_credential_first_and_no_resource_or_operation(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "github_tool")
    dialog = page.locator("#node-modal")
    labels = dialog.locator('.ge-settings__column[data-section="definition"] .field__label')
    assert [x.strip() for x in labels.all_inner_texts()] == ["Credential"]
    for label in ("Resource", "Operation", "Repository"):
        expect(dialog.get_by_label(label, exact=True)).to_have_count(
            0
        )  # the agent picks its calls itself
    expect(dialog.locator(".ge-inspector__icon")).to_have_attribute("title", re.compile("GitHub"))
    # read only until it is allowed; the switch, the timeout and the name for the model are offered through Add setting
    add_setting(page, "Allow writes")
    writes = dialog.get_by_label("Allow writes", exact=True)
    expect(writes).not_to_be_checked()
    writes.check()
    eventually(lambda: _config(api, definition, "github_tool")["allow_write"], True)
    add_setting(page, "Timeout (seconds)")
    expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_be_visible()


def test_the_github_mcp_node_shows_its_tool_list_only_for_selected_and_all_except(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _open(page, base_url, api, "github_tool")
    dialog = page.locator("#node-modal")
    expect(dialog.get_by_label("Tools to include", exact=True)).to_have_count(
        0
    )  # optional: offered through Add setting
    add_setting(page, "Tools to include")
    mode = dialog.get_by_label("Tools to include", exact=True)
    expect(mode).to_have_value("all")  # what applies until it is chosen
    expect(dialog.get_by_label("Tools", exact=True)).to_have_count(0)  # all tools: no list
    mode.select_option(label="selected")
    names = dialog.get_by_label("Tools", exact=True)
    expect(names).to_be_visible()
    names.fill("get_file_contents\nlist_commits")
    names.press("Tab")
    eventually(
        lambda: {
            k: _config(api, definition, "github_tool").get(k) for k in ("tools_mode", "tool_names")
        },
        {"tools_mode": "selected", "tool_names": "get_file_contents\nlist_commits"},
    )
    mode.select_option(label="all")
    expect(dialog.get_by_label("Tools", exact=True)).to_have_count(
        0
    )  # the list goes, what was written stays stored

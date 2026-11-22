"""Artifact types in the browser: the management page, the typed form of the artifact dialog, inline
errors, a second type without any code change, the dialog's size, the lock of a type in use, phone width."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import ConsoleMessage, Page, expect

from tests.e2e.helpers import Board, Dialog

SUPPORT = {
    "name": "Support triage",
    "fields": [
        {
            "name": "urgency",
            "label": "Urgency",
            "kind": "choice",
            "required": True,
            "default": "normal",
            "options": ["low", "normal", "high"],
        },
        {"name": "summary", "label": "Summary", "kind": "text", "required": True},
        {
            "name": "score",
            "label": "Score",
            "kind": "number",
            "min_value": 0,
            "max_value": 10,
            "integer_only": True,
        },
    ],
}
RELEASE = {
    "name": "Release",
    "fields": [
        {"name": "version", "label": "Version", "kind": "text", "required": True},
        {"name": "hotfix", "label": "Hotfix", "kind": "boolean"},
    ],
}


def make_type(api: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    response = api.post("/api/artifact-types", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def watch(page: Page) -> list[str]:
    """Console errors, warnings, policy violations and script errors."""
    problems: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type in ("error", "warning") or "Content Security Policy" in message.text:
            problems.append(message.text)

    page.on("console", console)
    page.on("pageerror", lambda e: problems.append(str(e)))
    return problems


def add_parameter(page: Page, label: str, kind: str, **settings: Any) -> None:
    """Add a row in the parameter editor and fill it: ``options``, ``required`` and other fields by key."""
    page.click("[data-add-field]")
    row = page.locator(".at-field").last
    row.locator("[data-key=label]").fill(label)
    row.locator("[data-key=kind]").select_option(kind)
    for key, value in settings.items():
        control = row.locator(f"[data-key={key}]")
        if isinstance(value, bool):
            control.set_checked(value)
        elif key == "default" and kind in ("choice", "boolean"):
            control.select_option(value)
        else:
            control.fill(str(value))


def create_type_in_the_ui(page: Page, name: str) -> None:
    page.click("[data-new-type]")
    page.fill("#name-modal-field-name", name)
    page.click("#name-modal [data-submit]")
    expect(page.locator("#fields-modal")).to_be_visible()


def save_parameters(page: Page) -> None:
    page.click("#fields-modal [data-submit]")
    expect(page.locator("#fields-modal")).to_be_hidden()


def new_artifact(page: Page, title: str, type_name: str | None = None) -> Dialog:
    page.locator('[data-create-task][data-status="backlog"]').click()
    dialog = Dialog(page)
    dialog.title_input.fill(title)
    if type_name:
        dialog.root.locator("#create-task-modal-field-type_id").select_option(label=type_name)
    return dialog


def test_two_types_with_their_own_parameters_are_made_and_used_in_the_browser(
    board: Board, api: httpx.Client
) -> None:
    page = board.page
    problems = watch(page)
    page.goto(f"{board.base_url}/artifact-types")
    expect(page.locator("[data-type-empty]")).to_be_visible()

    create_type_in_the_ui(page, "Support triage")
    add_parameter(page, "Urgency", "choice", options="low\nnormal\nhigh", required=True)
    page.locator(".at-field").last.locator("[data-key=default]").select_option("normal")
    add_parameter(page, "Summary", "text", required=True)
    add_parameter(page, "Score", "number", min_value=0, max_value=10, integer_only=True)
    save_parameters(page)
    expect(page.locator(".at-item .ge-item__meta")).to_have_text("3 parameters · 0 artifacts")

    # the typed form: required markers, the default, and the server's refusal inline with the typed values kept
    board.open()
    dialog = new_artifact(page, "Printer on fire", "Support triage")
    expect(page.locator("#param-urgency")).to_have_value("normal")
    expect(page.locator('label[for="param-summary"] .field__required')).to_be_visible()
    page.fill("#param-score", "99")
    dialog.root.locator("[data-submit]").click()
    expect(page.locator("#param-summary-error")).to_have_text("a value is required")
    expect(page.locator("#param-score-error")).to_have_text("99 is above the maximum 10")
    expect(page.locator("#param-score")).to_have_attribute("aria-invalid", "true")
    assert api.get("/api/tasks").json() == []
    expect(dialog.title_input).to_have_value("Printer on fire")
    page.fill("#param-summary", "Smoke from the printer")
    page.fill("#param-score", "7")
    dialog.root.locator("[data-submit]").click()
    expect(board.card("Printer on fire")).to_be_visible()
    expect(board.card("Printer on fire").locator(".task-card__meta")).to_have_text("Support triage")
    board.expect_field(
        "Printer on fire",
        "parameters",
        {"urgency": "normal", "summary": "Smoke from the printer", "score": 7},
    )
    assert problems == [] or all("422" in p for p in problems)  # the refused save is the only noise

    # a second type, other parameters, no code change
    page.goto(f"{board.base_url}/artifact-types")
    create_type_in_the_ui(page, "Release")
    add_parameter(page, "Version", "text", required=True)
    add_parameter(page, "Hotfix", "boolean")
    save_parameters(page)
    expect(page.locator(".at-item")).to_have_count(2)
    board.open()
    dialog = new_artifact(page, "Ship 1.2", "Release")
    expect(page.locator("#create-task-modal [data-form-params] .param")).to_have_count(2)
    expect(page.locator("#param-urgency")).to_have_count(0)
    page.fill("#param-version", "1.2.0")
    page.check("#param-hotfix")
    dialog.root.locator("[data-submit]").click()
    board.expect_field("Ship 1.2", "parameters", {"version": "1.2.0", "hotfix": True})
    stored = board.stored()
    assert stored["Ship 1.2"]["type_id"] != stored["Printer on fire"]["type_id"]

    dialog = board.open_card("Ship 1.2")
    expect(dialog.root.locator("[data-view-params]")).to_contain_text("1.2.0")
    expect(dialog.root.locator("[data-view-params]")).to_contain_text("Yes")


def test_the_editor_shows_a_refused_definition_at_its_row(board: Board, api: httpx.Client) -> None:
    make_type(api, {"name": "Ticket", "fields": []})
    page = board.page
    page.goto(f"{board.base_url}/artifact-types")
    page.click("[data-edit-fields]")
    add_parameter(page, "Urgency", "choice", options="low")  # one value is not a choice
    add_parameter(page, "Urgency", "text")
    page.click("#fields-modal [data-submit]")
    errors = page.locator("[data-row-error]:not([hidden])")
    expect(errors.first).to_contain_text("a choice has 2 to 20 allowed values")
    expect(page.locator("#fields-modal")).to_be_visible()  # nothing was lost
    page.locator(".at-field").last.locator("[data-move=up]").click()
    expect(page.locator(".at-field [data-key=kind]").first).to_have_value("text")


def test_the_dialog_keeps_its_size_between_view_and_edit(board: Board, api: httpx.Client) -> None:
    kind = make_type(api, SUPPORT)
    board.create(
        "Printer",
        body="It smokes",
        type_id=kind["id"],
        parameters={"summary": "Smoke", "score": 3},
    )
    dialog = board.open().open_card("Printer")
    expect(dialog.root.locator("[data-view-params] .param")).to_have_count(4)  # type + 3 parameters
    view = dialog.size()
    dialog.edit()
    dialog.settle()
    assert dialog.size() == view
    page = board.page
    page.fill("#param-score", "9")
    page.select_option("#param-urgency", "high")
    dialog.save()
    expect(dialog.root.locator("[data-view-params]")).to_contain_text("high")
    dialog.settle()
    assert dialog.size() == view
    board.expect_field("Printer", "parameters", {"urgency": "high", "summary": "Smoke", "score": 9})
    # unchanged parameters send nothing
    dialog.edit()
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.method) if r.method == "PATCH" else None)
    dialog.save()
    expect(dialog.view).to_be_visible()
    assert requests == []


def test_a_type_that_is_in_use_cannot_be_deleted_and_says_why(
    board: Board, api: httpx.Client
) -> None:
    kind = make_type(api, RELEASE)
    task = board.create("Ship", type_id=kind["id"], parameters={"version": "1"})
    page = board.page
    page.goto(f"{board.base_url}/artifact-types")
    item = page.locator(".at-item")
    expect(item.locator(".ge-item__meta")).to_have_text("2 parameters · 1 artifact")
    expect(item.locator(".at-item__hint")).to_contain_text("1 artifact uses this type")
    remove = item.locator("[data-delete]")
    expect(remove).to_have_attribute("aria-disabled", "true")
    remove.click(force=True)  # Playwright treats aria-disabled as disabled
    expect(page.locator("#confirm-modal")).to_be_hidden()
    assert api.delete(f"/api/artifact-types/{kind['id']}").status_code == 409
    api.delete(f"/api/tasks/{task['id']}")  # the page follows the events
    expect(item.locator(".at-item__hint")).to_be_hidden()
    remove.click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator("[data-type-empty]")).to_be_visible()
    assert api.get("/api/artifact-types").json() == []


def test_changing_the_type_asks_before_it_drops_values(board: Board, api: httpx.Client) -> None:
    support, release = make_type(api, SUPPORT), make_type(api, RELEASE)
    board.create("Printer", type_id=support["id"], parameters={"summary": "Smoke", "score": 3})
    dialog = board.open().open_card("Printer").edit()
    select = dialog.root.locator("#create-task-modal-field-type_id")
    confirm = dialog.root.locator("[data-type-confirm]")
    select.select_option(label="Release")
    expect(confirm).to_contain_text("drops the values of Urgency, Summary, Score")
    expect(select).to_have_value(support["id"])  # not changed yet
    dialog.root.locator("[data-type-keep]").click()
    expect(confirm).to_be_hidden()
    select.select_option(label="Release")
    dialog.root.locator("[data-type-switch]").click()
    expect(select).to_have_value(release["id"])
    expect(board.page.locator("#param-version")).to_be_visible()
    board.page.fill("#param-version", "2.0")
    dialog.save()
    board.expect_field("Printer", "type_id", release["id"])
    board.expect_field("Printer", "parameters", {"version": "2.0", "hotfix": False})


def test_pages_and_the_typed_dialog_work_at_phone_width(board: Board, api: httpx.Client) -> None:
    kind = make_type(api, SUPPORT)
    board.create("Printer", type_id=kind["id"], parameters={"summary": "Smoke"})
    page = board.page
    page.set_viewport_size({"width": 390, "height": 760})
    problems = watch(page)

    def fits() -> bool:
        return bool(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    page.goto(f"{board.base_url}/artifact-types")
    expect(page.locator(".at-item")).to_have_count(1)
    assert fits()
    page.click("[data-edit-fields]")
    expect(page.locator("#fields-modal")).to_be_visible()
    assert fits()
    box = page.locator("#fields-modal .modal__panel").bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    page.click("#fields-modal [data-cancel]")
    board.open()
    dialog = board.open_card("Printer").edit()
    expect(page.locator("#param-summary")).to_be_visible()
    assert fits()
    panel = dialog.root.locator(".modal__panel").bounding_box()
    assert panel is not None and panel["x"] >= 0 and panel["x"] + panel["width"] <= 390
    assert problems == []

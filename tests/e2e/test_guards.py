"""Guards in the browser (ADR-060): the guard library (its page under Pipeline next to Actions, New guard,
the guard editor with "Guard - NAME" (an en dash) renamed in place, no Name and no Start from row, the Logic part with its action,
Delete refused while used), attaching in the pipeline editor (the Guard entries open "Add a guard"), ONE shield per scope
with its plural tooltip and its popup (names, on/off, Detach, a name opens the editor), the rule builder's field select is
not cut, and a run proves what the guards do: a round guard with an escalation table fires at round 5 and 8 and pauses
the run, a stall guard stops a sleeping Code node; the History shows each firing with its facts."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _serve
from tests.e2e.helpers import Board, add_action, code_definition
from tests.helpers import build_pipeline, connect, graph_url, link, node

DASH = "\u2013"  # the title reads "Guard - NAME"
ROUND = {
    "type": "group",
    "mode": "all",
    "items": [{"type": "condition", "field": "runs", "op": "at_least", "value": 5}],
}


def _pipeline(client: httpx.Client, with_action: bool = False) -> dict[str, Any]:
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Watched"}).json()
    stage = node(client, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    pipeline["stage"] = stage
    if with_action:
        action = node(client, pipeline, "action", stage_id=stage["id"], x=60, y=48, name="Draft")
        connect(client, pipeline, stage, "start", action, "in")
        pipeline["action"] = action
    return pipeline


def _guard(client: httpx.Client, name: str = "Round guard", **extra: Any) -> dict[str, Any]:
    body = {
        "name": name,
        "trigger": {"type": "event", "events": ["enter"]},
        "when": ROUND,
        "consequence": "pause",
        **extra,
    }
    response = client.post("/api/guards", json=body)
    response.raise_for_status()
    created: dict[str, Any] = response.json()
    # a new definition is a draft and watches nothing (ADR-081): these tests are about guards that watch, so they publish it
    published = client.post(f"/api/guards/{created['id']}/publish")
    published.raise_for_status()
    guard: dict[str, Any] = published.json()["guard"]
    return guard


def _attach(
    client: httpx.Client, guard: dict[str, Any], pipeline: dict[str, Any], scope: str, scope_id: str
) -> dict[str, Any]:
    response = client.post(
        "/api/guard-attachments",
        json={
            "guard_id": guard["id"],
            "pipeline_id": pipeline["id"],
            "scope_type": scope,
            "scope_id": scope_id,
        },
    )
    response.raise_for_status()
    attachment: dict[str, Any] = response.json()
    return attachment


def _counts(api: httpx.Client, pipeline: dict[str, Any]) -> tuple[int, int]:
    graph = api.get(graph_url(pipeline)).json()
    return len(graph["nodes"]), len(graph["edges"])


def _open(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _window(page: Page) -> Any:
    window = page.locator("#guard-modal")
    expect(window).to_be_visible()
    return window


def _popup(page: Page) -> Any:
    popup = page.locator("[data-guard-popover]")
    expect(popup).to_be_visible()
    return popup


def _attach_through_dialog(page: Page, text: str) -> None:
    """The popup's "Attach guard": the attach dialog, a combobox typed into, the choice, Attach."""
    popup = _popup(page)
    popup.get_by_role("button", name="Attach guard").click()
    dialog = page.locator("#guard-attach-modal")
    expect(dialog).to_be_visible()
    dialog.get_by_role("combobox", name="Guard").fill(text)
    dialog.locator(".combobox__option", has_text=text).first.click()
    dialog.get_by_role("button", name="Attach", exact=True).click()
    expect(dialog).to_be_hidden()


# ── the library page ─────────────────────────────────────────────────


def test_actions_and_guards_are_two_sub_entries_of_the_pipeline_section(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/actions")
    section = page.locator(".sidebar .nav-section")
    children = section.locator(".nav-list .nav-link")
    expect(children).to_have_text(["Actions", "Guards", "Agents"])
    expect(children.nth(0)).to_have_attribute("aria-current", "page")
    children.nth(1).click()
    expect(page).to_have_url(f"{base_url}/guards")
    expect(page.locator(".sidebar .nav-section .nav-link[aria-current=page]")).to_have_text(
        "Guards"
    )
    expect(page.locator(".mg__empty")).to_contain_text("No guards yet.")
    page.locator(".sidebar .nav-section .nav-list .nav-link", has_text="Actions").click()
    expect(page).to_have_url(f"{base_url}/actions")  # the existing route stays


def test_new_guard_opens_a_blank_editor_in_one_click_and_the_templates_are_gone(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """Owner's decision (templates removed, ADR-060 addendum): the button is a plain button, not a menu of a blank guard and
    templates; one click opens the editor with a blank definition whose name is typed first. Nothing is stored until it is saved."""
    page.goto(f"{base_url}/guards")
    button = page.get_by_role("button", name="New guard")
    expect(button).not_to_have_attribute("aria-haspopup", "menu")
    button.click()
    expect(page.get_by_role("menu")).to_have_count(
        0
    )  # no menu: no 'Blank guard', no 'From template'
    window = _window(page)
    expect(window).to_be_visible()
    expect(window).not_to_contain_text("Start from")
    expect(
        window.get_by_role("textbox", name="Guard name")
    ).to_be_visible()  # the title starts as its name field
    expect(window.locator("[data-guard-used]")).to_have_text("Not used yet")
    sections = window.locator("[data-section]")
    expect(sections).to_have_count(
        5
    )  # the form is drawn from the manifest: trigger, then, condition, escalation, logic
    # a consequence that is not built yet is greyed and says so in its name: "<name> | WIP" (work in progress)
    consequence = window.locator("[data-field-key=consequence]")
    expect(consequence.locator("option", has_text="Notify")).to_have_text("Notify | WIP")
    expect(consequence.locator("option", has_text="Notify")).to_be_disabled()
    for key, title in {
        "trigger": "Trigger",
        "then": "Then",
        "condition": "Condition",
        "escalation": "Escalation steps",
        "logic": "Logic",
    }.items():
        expect(window.locator(f"[data-section={key}] .fv-section__title")).to_contain_text(title)
    window.get_by_role("button", name="Cancel").click()
    assert api.get("/api/guards").json() == []  # a blank guard that was never saved is not stored
    # the two template routes no longer exist
    assert api.get("/api/guards/templates").status_code in (404, 405, 422)
    assert api.post("/api/guards/from-template", json={"template": "stall"}).status_code in (
        404,
        405,
    )


def test_a_published_guard_card_shows_what_fires_it_its_condition_in_words_and_where_it_is_used(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _guard(
        api,
        "Stall guard",
        trigger={
            "type": "interval",
            "every_seconds": 60,
            "for_seconds": 0,
            "cooldown_seconds": 600,
        },
        when={
            "type": "group",
            "mode": "all",
            "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 900}],
        },
    )
    page.goto(f"{base_url}/guards")
    item = page.locator(".mg-card")
    expect(item.locator(".mg-card__name")).to_have_text("Stall guard")
    # what fires it, its condition in words, its consequence and where it is used: chips and one line (before: one summary line)
    chips = item.locator(".mg-card__chips .ge-chip")
    expect(chips).to_have_text(["Every 1 minute", "Pause the run", "v1 published"])
    # the condition in words is the card's middle text (the uniform cards of ADR-069), the facts line holds where it is used
    expect(item.locator(".mg-card__text")).to_have_text(
        "Time without progress is at least 15 minutes"
    )
    expect(item.locator("[data-used]")).to_have_text("Not used yet")


def test_the_title_renames_the_guard_in_place_and_refuses_an_empty_name(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _guard(api, "Loop watch")
    page.goto(f"{base_url}/guards")
    page.locator(".mg-card [data-edit]").click()  # the pencil opens the guard editor
    window = _window(page)
    name = window.locator("[data-guard-name]")
    expect(name).to_have_accessible_name("Guard name: Loop watch. Click to edit")
    name.focus()
    page.keyboard.press("Enter")
    field = window.get_by_role("textbox", name="Guard name")
    field.fill("")
    page.keyboard.press("Enter")
    expect(window.locator(".inline-name__error")).to_have_text("Give the guard a name.")
    expect(field).to_be_visible()  # still open: a definition needs a name
    field.fill("Stall watch")
    page.keyboard.press("Escape")  # only leaves the field
    expect(window).to_be_visible()
    expect(window.locator(".modal__title")).to_have_text(f"Guard {DASH} Loop watch")
    name.click()
    field.fill("Stall watch")
    page.keyboard.press("Enter")
    expect(window.locator(".modal__title")).to_have_text(f"Guard {DASH} Stall watch")
    window.get_by_role("button", name="Save").click()
    expect(window).to_be_hidden()
    expect(page.locator(".mg-card .mg-card__name")).to_have_text("Stall watch")
    assert [g["name"] for g in api.get("/api/guards").json()] == ["Stall watch"]


def test_the_field_select_of_a_condition_shows_its_whole_name(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _guard(api, "Idle", when={"type": "group", "mode": "all", "items": []})
    page.goto(f"{base_url}/guards")
    page.locator(".mg-card [data-edit]").click()  # the pencil opens the guard editor
    window = _window(page)
    window.get_by_role("button", name="Add condition").click()
    field = window.locator(".rb-row .rb-select").first
    field.select_option(label="Time without progress")
    expect(field).to_have_attribute("title", "Time without progress")
    # a dialog is as small as its content allows (ADR-059): the row of a condition at the least width it can take
    field.evaluate("el => { el.closest('.rb-row').style.width = 'min-content'; }")
    cut = field.evaluate(
        """el => {
            const probe = document.createElement('span');
            const style = getComputedStyle(el);
            probe.style.font = style.font;
            probe.style.position = 'absolute';
            probe.style.whiteSpace = 'nowrap';
            probe.textContent = el.selectedOptions[0].textContent;
            document.body.append(probe);
            const text = probe.getBoundingClientRect().width;
            probe.remove();
            const room = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
            return text - room;
        }"""
    )
    assert cut <= 0, f"the name is cut by {cut:.1f} px"


def test_the_logic_part_makes_the_guards_action_and_opens_it_with_the_way_back(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    _guard(api, "Judge rounds")
    page.goto(f"{base_url}/guards")
    page.locator(".mg-card [data-edit]").click()  # the pencil opens the guard editor
    window = _window(page)
    logic = window.locator("[data-section=logic]")
    expect(logic).to_contain_text("the guard runs no action of its own")
    logic.get_by_role("button", name="Run an action when it fires").click()
    expect(window.locator("[data-field-key=consequence]")).to_have_value("run_action")
    chooser = logic.locator("[data-guard-action]")
    expect(chooser.locator("option:checked")).to_have_text("None yet")
    logic.get_by_role("button", name="New").click()
    expect(chooser.locator("option:checked")).to_have_text("Judge rounds (guard)")
    logic.get_by_role("button", name="Edit").click()  # saves first, then the action editor
    page.wait_for_url("**/actions/**")
    back = page.locator("[data-back]")
    expect(back).to_have_text("Back to Judge rounds")
    [guard] = api.get("/api/guards").json()
    assert guard["consequence"] == "run_action" and guard["action_id"]
    assert api.get(f"/api/actions/{guard['action_id']}").json()["graph"]["name"] == (
        "Judge rounds (guard)"
    )
    back.click()
    expect(_window(page).locator(".modal__title")).to_have_text(f"Guard {DASH} Judge rounds")


def test_a_used_guard_cannot_be_deleted_until_it_is_detached(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    guard = _guard(api)
    attachment = _attach(api, guard, pipeline, "stage", pipeline["stage"]["id"])
    page.goto(f"{base_url}/guards")
    item = page.locator(".mg-card")
    expect(item.locator("[data-used]")).to_have_text("Used in 1 place")
    bin = item.locator("[data-delete]")
    expect(bin).to_have_attribute("aria-disabled", "true")
    expect(bin).to_have_attribute("title", "Detach it first: it is used in 1 place")
    bin.click(force=True)  # aria-disabled: it stays focusable and says why
    expect(page.locator("[data-alert]")).to_contain_text("Detach it first")
    expect(page.locator("#confirm-modal")).to_be_hidden()
    item.locator("[data-edit]").click()
    window = _window(page)
    expect(window.locator("[data-guard-used]")).to_have_text(
        "Used in 1 place. Only the published version applies."
    )
    window.locator("[data-delete]").click(force=True)
    expect(window.locator("[data-form-error]")).to_have_text(
        "Detach it first: it is used in 1 place"
    )
    window.get_by_role("button", name="Cancel").click()
    api.delete(f"/api/guard-attachments/{attachment['id']}").raise_for_status()
    page.reload()
    page.locator(".mg-card [data-delete]").click()
    page.locator("#confirm-modal [data-confirm], #confirm-modal [data-submit]").first.click()
    expect(page.locator(".mg-card")).to_have_count(0)
    assert api.get("/api/guards").json() == []


# ── attaching in the pipeline editor ─────────────────────────────────


def test_the_pipelines_guard_entry_attaches_a_library_guard_and_its_shield_appears_next_to_the_plus(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _guard(api, "Round guard")
    _guard(api, "Stall guard")
    _guard(api, "Stage only", scope_types=["stage"])
    before = _counts(api, pipeline)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    shield = page.locator("[data-pipeline-shield]")
    expect(shield).to_be_hidden()  # no guard attached yet
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    items = page.locator(".ge-add__item")
    assert [i.split("\n")[0] for i in items.all_inner_texts()][:3] == ["Stage", "Pipeline", "Guard"]
    page.locator("[data-placeholder=guard]").click()
    popup = _popup(page)
    expect(popup).to_have_accessible_name("Add a guard")
    expect(popup.get_by_role("searchbox")).to_have_count(
        0
    )  # no search: few guards hang on one scope
    expect(popup.get_by_role("button", name="New guard")).to_have_class(
        re.compile(r"button--primary")
    )
    _attach_through_dialog(page, "Stall")
    expect(shield).to_be_visible()
    expect(shield).to_have_attribute("title", "1 guard configured")
    expect(popup.locator(".gd-attached__name")).to_have_text(["Stall guard"])
    page.keyboard.press("Escape")
    expect(popup).to_be_hidden()
    expect(page.locator("[data-add-menu]")).to_be_focused()
    [place] = api.get("/api/guard-attachments", params={"pipeline_id": pipeline["id"]}).json()
    assert (place["name"], place["scope_type"], place["scope_id"]) == (
        "Stall guard",
        "pipeline",
        pipeline["id"],
    )
    assert _counts(api, pipeline) == before, "a guard is never a node"


def test_a_stage_guard_is_attached_from_its_plus_and_its_shield_popup_switches_detaches_and_opens_it(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _guard(api, "Round guard")
    _guard(api, "Health guard", scope_types=["stage"])
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    header = page.locator(".ge-stage__header")
    expect(header.locator("[data-guard-shield]")).to_have_count(0)
    plus = page.locator("[data-stage-add]")
    plus.focus()
    page.keyboard.press("Enter")  # the keyboard reaches the menu as before
    menu = page.get_by_role("menu", name="Add to stage")
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Guard")).to_be_focused()
    page.keyboard.press("Enter")
    _popup(page)
    _attach_through_dialog(page, "Round guard")
    _attach_through_dialog(page, "Health guard")
    popup = _popup(page)
    expect(popup.get_by_role("button", name="Attach guard")).to_have_attribute(
        "aria-disabled", "true"
    )
    expect(popup).to_contain_text("No other guard to attach.")
    page.keyboard.press("Escape")

    shield = header.locator("[data-guard-shield]")
    expect(shield).to_have_count(1)  # ONE shield, not a chip per guard
    expect(shield).to_have_attribute("title", "2 guards configured")
    expect(shield).to_have_accessible_name("2 guards configured: Gap Analysis")
    shield.click()
    popup = _popup(page)
    expect(popup).to_have_accessible_name("Guards of Gap Analysis")
    names = popup.locator(".gd-attached__name")
    expect(names).to_have_text(["Health guard", "Round guard"])
    expect(names.first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(popup.get_by_role("button", name="Detach Health guard")).to_be_focused()
    switch = popup.get_by_role("switch", name="Round guard on or off here")
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(popup.locator(".gd-attached.is-off .gd-attached__name")).to_have_text("Round guard")
    expect(shield).to_have_attribute("title", "2 guards configured")  # configured, on or off
    off = [a for a in api.get("/api/guard-attachments").json() if a["name"] == "Round guard"]
    assert off[0]["enabled"] is False
    popup.get_by_role("button", name="Detach Health guard").click()
    expect(names).to_have_text(["Round guard"])
    expect(shield).to_have_attribute("title", "1 guard configured")
    names.first.click()
    window = _window(page)
    expect(window.locator(".modal__title")).to_have_text(f"Guard {DASH} Round guard")
    expect(window.locator("[data-guard-used]")).to_have_text(
        "Used in 1 place. Only the published version applies."
    )
    expect(window).not_to_contain_text("Start from")
    page.keyboard.press("Escape")
    shield.click()
    _popup(page).get_by_role("button", name="Detach Round guard").click()
    expect(header.locator("[data-guard-shield]")).to_have_count(0)
    assert api.get("/api/guard-attachments").json() == []


def test_a_new_guard_made_from_an_actions_menu_is_attached_to_it_and_its_card_shows_the_shield(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api, with_action=True)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    card = page.locator(".ge-node--action")
    expect(card.locator("[data-guard-shield]")).to_have_count(0)
    card.locator(".ge-node__name").click(button="right")
    menu = page.get_by_role("menu")
    labels = [e.split("\n")[0] for e in menu.get_by_role("menuitem").all_inner_texts()]
    assert labels.index("Guard") == len(labels) - 2 and labels[-1] == "Delete", labels
    menu.get_by_role("menuitem", name="Guard").click()
    popup = _popup(page)
    expect(popup).to_contain_text("No other guard to attach.")
    popup.get_by_role("button", name="New guard").click()
    window = _window(page)
    expect(window).to_contain_text(
        "Saving adds it to the library and attaches it to the action Draft."
    )
    page.keyboard.type("Draft watch")  # the title is the name field of a new guard
    page.keyboard.press("Enter")
    expect(window.locator(".modal__title")).to_have_text(f"Guard {DASH} Draft watch")
    window.get_by_role("button", name="Add condition").click()
    window.get_by_role("button", name="Save").click()
    expect(window).to_be_hidden()
    badge = card.locator("[data-guard-shield]")
    expect(badge).to_have_attribute("title", "1 guard configured")
    [guard] = api.get("/api/guards").json()
    assert guard["name"] == "Draft watch" and guard["used_by"] == 1
    assert guard["attachments"][0]["scope_id"] == pipeline["action"]["id"]
    card.locator(".ge-node__name").dblclick()
    section = page.locator("[data-guard-section]")
    expect(section).to_contain_text("Draft watch")
    expect(section.get_by_role("button", name="Add guard")).to_be_visible()


def test_an_action_definition_offers_a_guard_in_its_plus_menu(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """It may watch the whole action and each of its nodes (tests/e2e/test_guard_scopes.py has the rest)."""
    definition = api.post("/api/actions", json={"name": "Check"}).json()
    _open(page, base_url, f"/actions/{definition['slug']}")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "guard")
    expect(page.locator("[data-placeholder=guard]")).to_have_count(1)


def test_adding_an_action_through_the_stage_menu_still_works(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    add_action(page)
    expect(page.locator(".ge-node--action")).to_have_count(1)


def test_the_guards_page_and_the_shield_speak_german(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    for name in ("A", "B"):
        _attach(api, _guard(api, name), pipeline, "stage", pipeline["stage"]["id"])
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    page.goto(f"{base_url}/guards")
    expect(page.locator(".sidebar .nav-section .nav-link[aria-current=page]")).to_have_text(
        "Wächter"
    )
    expect(page.locator(".mg-card [data-used]").first).to_have_text("Verwendet an 1 Stelle")
    _open(page, base_url, f"/pipelines/{pipeline['slug']}")
    shield = page.locator(".ge-stage__header [data-guard-shield]")
    expect(shield).to_have_attribute("title", "2 Wächter eingerichtet")


# ── what guards do in a run (a server with a short minimum interval) ──


@pytest.fixture(scope="module")
def guard_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    yield from _serve(
        Path(tmp_path_factory.mktemp("guards")),
        guard_min_interval_seconds="0.5",
        heartbeat_min_spacing_seconds="0.5",
    )


@pytest.fixture
def guard_api(guard_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=guard_url, timeout=30) as client:
        for task in client.get("/api/tasks").json():
            client.post(f"/api/tasks/{task['id']}/run/stop")
            client.delete(f"/api/tasks/{task['id']}")
        for path in ("/api/pipelines", "/api/actions"):
            for graph in client.get(path).json():
                client.delete(f"{path}/{graph['id']}")
        for guard in client.get("/api/guards").json():
            client.delete(f"/api/guards/{guard['id']}")
        yield client


def _run(client: httpx.Client, pipeline: dict[str, Any], title: str) -> dict[str, Any]:
    task: dict[str, Any] = client.post(
        "/api/tasks", json={"title": title, "status": "backlog"}
    ).json()
    client.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]}
    ).raise_for_status()
    return task


def _status(client: httpx.Client, task: dict[str, Any], status: str) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        return next(r for r in client.get("/api/runs").json() if r["task_id"] == task["id"])

    Board._eventually(lambda: run()["status"], status, 30)
    return run()


def _guard_rows(page: Page, guard_url: str, client: httpx.Client, title: str) -> Any:
    board = Board(page, guard_url, client)
    dialog = board.open().open_card(title).open_history()
    return dialog.history.locator('.history-event[data-kind="guard"]')


def test_a_round_guard_fires_at_round_5_and_8_and_pauses_the_run_and_the_history_says_why(
    page: Page, guard_url: str, guard_api: httpx.Client
) -> None:
    pipeline = build_pipeline(guard_api, stages=1, name="Loop")
    stage, work = pipeline["stages"][0]
    check = node(guard_api, pipeline, "action", stage_id=stage["id"], x=240, y=48, name="Check")
    connect(guard_api, pipeline, work, "pass", check, "in")
    connect(
        guard_api, pipeline, check, "pass", work, "in"
    )  # a loop back to the stage's entry action
    judge = code_definition(
        guard_api,
        "Judge",
        'import json, sys\nsys.exit(0 if json.load(open("context.json"))["vars"]["guard_firing"] < 2 else 1)',
        purpose="guard",
    )
    health = _guard(
        guard_api,
        "Health guard",
        when={
            "type": "group",
            "mode": "all",
            "items": [{"type": "condition", "field": "runs", "op": "at_least", "value": 1}],
        },
        consequence="run_action",
        fallback="pause",
        action_id=judge["id"],
        escalation=[{"from_firing": 1, "every_runs": 5}, {"from_firing": 2, "every_runs": 3}],
    )
    _attach(guard_api, health, pipeline, "stage", stage["id"])
    task = _run(guard_api, pipeline, "Looping")
    run = _status(guard_api, task, "stopped")
    assert run["note"].startswith("Paused by guard Health guard fired at Stage 1: round 8")

    rows = _guard_rows(page, guard_url, guard_api, "Looping")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Health guard")
    expect(rows.nth(0)).to_contain_text("fired at Stage 1: paused the run (round 8")
    expect(rows.nth(1)).to_contain_text("fired at Stage 1: the run went on (round 5")
    expect(rows.nth(0).locator(".history-marker")).to_have_attribute("data-tone", "accent")
    assert rows.nth(0).get_attribute("data-group") == "runs"


def test_a_stall_guard_stops_a_sleeping_code_node_and_aborts_the_run(
    page: Page, guard_url: str, guard_api: httpx.Client
) -> None:
    pipeline = build_pipeline(guard_api, stages=1, name="Stall")
    _stage, action = pipeline["stages"][0]
    link(
        guard_api,
        pipeline,
        action,
        code_definition(guard_api, "Sleeper", "import time\ntime.sleep(60)"),
    )
    stall = _guard(
        guard_api,
        "Stall guard",
        trigger={"type": "interval", "every_seconds": 1, "for_seconds": 1},
        when={
            "type": "group",
            "mode": "all",
            "items": [{"type": "condition", "field": "idle", "op": "at_least", "value": 2}],
        },
        consequence="abort",
    )
    _attach(guard_api, stall, pipeline, "action", action["id"])
    task = _run(guard_api, pipeline, "Stalling")
    run = _status(guard_api, task, "failed")
    assert run["note"].startswith("Aborted by guard Stall guard fired at ")
    rows = _guard_rows(page, guard_url, guard_api, "Stalling")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("aborted the run")
    expect(rows.first).to_contain_text("without progress")
    expect(rows.first.locator(".history-marker")).to_have_attribute("data-tone", "bad")

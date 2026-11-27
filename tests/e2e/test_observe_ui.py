"""The observe mode in the editor (ADR-088): the switch in the Dry run tab of a pipeline's Trigger window, the status bar of the canvas (the eye, the
stop sign, the shield and the plus, in a fixed order), the popups of the eye and of the refused starts, and the chips of the management page.
The rules themselves (what an observed run does, the end, release) are the server's and are tested in tests/test_observe_mode.py and
tests/test_observe_api.py; these tests drive a real browser against the API."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import eventually
from tests.e2e.test_dry_run_tab import _commenting_pipeline, _dry_run_tab, _open_trigger
from tests.e2e.test_guards import _attach, _guard
from tests.helpers import graph_url, post

DIALOG = "#node-modal"


def _observe(api: httpx.Client, pipeline: dict[str, Any], **setting: Any) -> dict[str, Any]:
    """Set the mode in the draft and publish it (one call, as a remote tool would)."""
    response = api.put(
        f"/api/pipelines/{pipeline['id']}/observe",
        json={"enabled": True, "publish": True, **setting},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _read(api: httpx.Client, pipeline: dict[str, Any]) -> dict[str, Any]:
    return dict(api.get(f"/api/pipelines/{pipeline['id']}/observe").json())


def _pipeline(api: httpx.Client, name: str = "Commenting") -> dict[str, Any]:
    pipeline, _ = _commenting_pipeline(api)
    if name != "Commenting":
        api.patch(graph_url(pipeline), json={"name": name}).raise_for_status()
    return pipeline


def _start(api: httpx.Client, pipeline: dict[str, Any]) -> httpx.Response:
    task = post(api, "/api/tasks", title="Observed card", status="backlog")
    return api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})


def _run_until_ended(api: httpx.Client, pipeline: dict[str, Any]) -> None:
    """One observed run uses up a limit of one run; the next start is refused."""
    _start(api, pipeline).raise_for_status()
    eventually(lambda: _read(api, pipeline)["state"]["ended"], True, timeout=15)


def _open(page: Page, base_url: str, pipeline: dict[str, Any]) -> None:
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _entry(page: Page, key: str) -> Locator:
    return page.locator(f'[data-status-entry="{key}"]')


def _guard_on_the_pipeline(api: httpx.Client, pipeline: dict[str, Any]) -> None:
    guard = _guard(api, "Bar guard")
    _attach(api, guard, pipeline, "pipeline", pipeline["id"])


def test_the_observe_switch_is_in_the_dry_run_tab_of_a_pipeline_and_not_of_an_action(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline, definition = _commenting_pipeline(api)
    dialog = _open_trigger(page, base_url, api, pipeline)
    panel = _dry_run_tab(dialog)
    switch = panel.get_by_role("switch", name="Observe")
    expect(switch).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(panel.get_by_text("Every run of this pipeline runs as a dry run")).to_be_visible()
    expect(
        panel.locator('[data-observe-limit="days"]')
    ).to_be_hidden()  # the limits come with the switch on
    page.keyboard.press("Escape")
    action = _open_trigger(page, base_url, api, definition, kind="actions")
    action_panel = _dry_run_tab(action)
    expect(action_panel.locator("[data-observe-panel]")).to_have_count(0)


def test_switching_on_changes_the_draft_shows_the_limits_and_says_it_applies_when_published(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    dialog = _open_trigger(page, base_url, api, pipeline)
    panel = _dry_run_tab(dialog)
    status = panel.locator("[data-observe-status]")
    panel.get_by_role("switch", name="Observe").click()
    days, runs = (
        panel.locator('[data-observe-limit="days"]'),
        panel.locator('[data-observe-limit="runs"]'),
    )
    expect(days).to_be_visible()
    expect(runs).to_be_visible()
    expect(
        panel.get_by_text("starts are refused until you release or observe again")
    ).to_be_visible()
    expect(status).to_have_text("Applies when you publish. Live now: not observing.")
    eventually(lambda: _read(api, pipeline)["draft"], {"enabled": True, "days": None, "runs": None})
    assert _read(api, pipeline)["published"] is None, "only a publication makes it so"
    expect(_entry(page, "observe")).to_be_hidden()  # no eye: nothing observes yet
    days.fill("many")
    days.blur()
    expect(panel.locator(".ge-observe__error")).to_have_text("Enter a whole number.")
    days.fill("400")
    days.blur()
    expect(panel.locator(".ge-observe__error")).to_have_text("Enter a number from 1 to 365.")
    days.fill("7")
    runs.fill("5")
    runs.blur()
    eventually(lambda: _read(api, pipeline)["draft"], {"enabled": True, "days": 7, "runs": 5})
    expect(panel.locator(".ge-observe__error")).to_be_hidden()
    panel.get_by_role("switch", name="Observe").click()
    expect(days).to_be_hidden()
    eventually(
        lambda: _read(api, pipeline)["draft"], {"enabled": False, "days": None, "runs": None}
    )


def test_the_eye_is_there_only_while_the_published_mode_observes_and_its_popup_stops_it_in_the_draft(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline)
    expect(_entry(page, "observe")).to_be_hidden()
    _observe(api, pipeline, runs=50)
    _open(page, base_url, pipeline)
    eye = _entry(page, "observe")
    expect(eye).to_be_visible()
    expect(eye).to_have_accessible_name("Observe mode: every run is a dry run")
    eye.click()
    popup = page.locator(".status-popup")
    expect(popup).to_be_visible()
    expect(popup).to_contain_text("Observe mode")
    expect(popup).to_contain_text("0 of 50 runs observed")
    expect(popup).to_contain_text("Observing since")
    popup.get_by_role("button", name="Stop observing").click()
    expect(popup).to_contain_text("Stop observing? The change applies when you publish.")
    popup.get_by_role("button", name="Cancel").click()
    expect(popup).not_to_contain_text("Stop observing? The change")
    popup.get_by_role("button", name="Stop observing").click()
    popup.get_by_role("button", name="Stop observing").click()  # the question's own button
    expect(popup).to_contain_text("Switched off in the draft. It applies when you publish.")
    assert _read(api, pipeline)["draft"]["enabled"] is False
    assert _read(api, pipeline)["published"]["enabled"] is True, "live until a publication"
    expect(_entry(page, "observe")).to_be_visible()
    expect(page.locator(".ge-bar__state")).to_contain_text(
        "Draft"
    )  # the draft differs from the published version now


def test_open_settings_in_the_popup_of_the_eye_opens_the_trigger_window_at_the_dry_run_tab(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _observe(api, pipeline)
    _open(page, base_url, pipeline)
    _entry(page, "observe").click()
    page.locator(".status-popup").get_by_role("button", name="Open settings").click()
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("tab", name="Dry run")).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("switch", name="Observe")).to_have_attribute("aria-checked", "true")
    expect(dialog.locator("[data-observe-status]")).to_have_text(
        "Applies when you publish."
    )  # the draft and what is live agree


def _boxes(page: Page, keys: list[str]) -> dict[str, Any]:
    out = {}
    for key in keys:
        box = page.locator(f'[data-status-entry="{key}"]').bounding_box()
        assert box, key
        out[key] = box
    return out


def test_the_status_bar_is_the_eye_then_the_shield_then_the_plus_without_a_gap(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _observe(api, pipeline)
    _open(page, base_url, pipeline)
    expect(_entry(page, "guard")).to_be_hidden()
    eye_only = _boxes(page, ["observe", "add"])
    gap = eye_only["add"]["x"] - (eye_only["observe"]["x"] + eye_only["observe"]["width"])
    assert 0 <= gap <= 8, gap  # no shield: the eye sits next to the plus, no empty place
    plus_edge = eye_only["add"]["x"] + eye_only["add"]["width"]
    _guard_on_the_pipeline(api, pipeline)
    _open(page, base_url, pipeline)
    expect(_entry(page, "guard")).to_be_visible()
    three = _boxes(page, ["observe", "guard", "add"])
    assert three["observe"]["x"] < three["guard"]["x"] < three["add"]["x"], three
    for left, right in (("observe", "guard"), ("guard", "add")):
        between = three[right]["x"] - (three[left]["x"] + three[left]["width"])
        assert 0 <= between <= 8, (left, right, between)
    assert abs(three["add"]["x"] + three["add"]["width"] - plus_edge) <= 1, (
        "the plus stays at the right edge"
    )
    # the shield keeps doing what it did: a click opens the guards of the pipeline
    _entry(page, "guard").click()
    expect(page.locator("[data-guard-popover]")).to_be_visible()
    assert [
        e.get_attribute("data-status-entry")
        for e in page.locator("[data-status-entry]:visible").all()
    ] == ["observe", "guard", "add"]


def test_the_stop_sign_shows_while_starts_are_refused_and_its_popup_decides_at_once(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _observe(api, pipeline, runs=1)
    _run_until_ended(api, pipeline)
    refused = _start(api, pipeline)
    assert refused.status_code == 409 and refused.json()["code"] == "observation_ended"
    _open(page, base_url, pipeline)
    stop = _entry(page, "ended")
    expect(stop).to_be_visible()
    expect(_entry(page, "observe")).to_be_hidden()  # an eye and a stop sign are never both there
    expect(stop).to_have_accessible_name("Starts are refused: the observation ended")
    stop.click()
    popup = page.locator(".status-popup")
    expect(popup).to_contain_text("Starts refused")
    expect(popup).to_contain_text("has ended")
    expect(popup.get_by_role("button", name="Release")).to_be_visible()
    popup.get_by_role("button", name="Observe again").click()
    expect(_entry(page, "ended")).to_be_hidden()
    expect(_entry(page, "observe")).to_be_visible()
    state = _read(api, pipeline)["state"]
    assert state["observing"] is True and state["ended"] is False and state["runs_done"] == 0
    assert (
        _start(api, pipeline).status_code == 201
    )  # a start is accepted again, no publication needed


def test_release_in_the_popup_lets_the_pipeline_run_for_real_and_removes_the_entry(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _observe(api, pipeline, runs=1)
    _run_until_ended(api, pipeline)
    _open(page, base_url, pipeline)
    _entry(page, "ended").click()
    page.locator(".status-popup").get_by_role("button", name="Release").click()
    expect(_entry(page, "ended")).to_be_hidden()
    expect(_entry(page, "observe")).to_be_hidden()
    state = _read(api, pipeline)["state"]
    assert state["released"] is True and state["ended"] is False
    assert [e["action"] for e in state["events"]][-1] == "release"


def test_the_management_page_has_a_chip_for_an_observed_pipeline_and_one_for_refused_starts(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    watched = _pipeline(api, "Watched")
    _observe(api, watched)
    stopped, _ = _commenting_pipeline(api)
    api.patch(graph_url(stopped), json={"name": "Stopped"}).raise_for_status()
    _observe(api, stopped, runs=1)
    _run_until_ended(api, stopped)
    page.goto(f"{base_url}/pipelines")
    expect(page.locator('[data-observe="observing"]')).to_have_count(1)
    expect(page.locator('[data-observe="observing"]')).to_have_text("Observing")
    expect(page.locator('[data-observe="ended"]')).to_have_count(1)
    expect(page.locator('[data-observe="ended"]')).to_have_text("Starts refused")


def test_changing_the_inputs_of_the_trigger_keeps_the_observe_setting_of_the_draft(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    dialog = _open_trigger(page, base_url, api, pipeline)
    panel = _dry_run_tab(dialog)
    panel.get_by_role("switch", name="Observe").click()
    eventually(lambda: (_read(api, pipeline)["draft"] or {}).get("enabled"), True)
    dialog.get_by_role("tab", name="Inputs").click()
    dialog.locator(".sf__add").click()
    dialog.get_by_label("Name of field 1").fill("who")
    dialog.get_by_label("Name of field 1").press("Enter")
    eventually(
        lambda: [i["name"] for i in (_trigger_config(api, pipeline) or {}).get("inputs", [])],
        ["who"],
    )
    assert _read(api, pipeline)["draft"]["enabled"] is True, "the inputs did not wipe the mode"


def _trigger_config(api: httpx.Client, pipeline: dict[str, Any]) -> dict[str, Any] | None:
    nodes = api.get(graph_url(pipeline)).json()["nodes"]
    return next((n["config"] for n in nodes if n["kind"] == "trigger"), None)

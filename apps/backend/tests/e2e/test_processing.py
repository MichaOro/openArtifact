"""Processing an artifact in a pipeline: start and stop in the dialog, and the lock while it runs."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import expect

from tests.e2e.helpers import Board


def _url(graph: dict[str, Any]) -> str:
    return f"/api/{'actions' if graph['kind'] == 'action' else 'pipelines'}/{graph['id']}"


def _post(api: httpx.Client, url: str, **body: Any) -> dict[str, Any]:
    response = api.post(url, json=body)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _slow_pipeline(api: httpx.Client) -> dict[str, Any]:
    """trigger → stage → complete; the stage's action waits 30 s (a timer in its definition)."""
    for path in ("/api/pipelines", "/api/actions"):
        for graph in api.get(path).json():
            api.delete(f"{path}/{graph['id']}")
    pipeline = _post(api, "/api/pipelines", name="Flow")
    graph = api.get(_url(pipeline)).json()
    trigger = next(n for n in graph["nodes"] if n["kind"] == "trigger")
    complete = next(n for n in graph["nodes"] if n["kind"] == "complete")
    base = _url(pipeline)
    stage = _post(api, f"{base}/nodes", kind="stage", name="Gap analysis")
    action = _post(api, f"{base}/nodes", kind="action", stage_id=stage["id"], x=24, y=48)

    def edge(a: dict[str, Any], ap: str, b: dict[str, Any], bp: str) -> None:
        _post(
            api,
            f"{base}/edges",
            source_id=a["id"],
            source_port=ap,
            target_id=b["id"],
            target_port=bp,
        )

    edge(trigger, "out", stage, "start")
    edge(stage, "start", action, "in")
    edge(action, "pass", stage, "end")
    edge(stage, "end", complete, "in")

    definition = _post(api, "/api/actions", name="Wait")
    dbase = _url(definition)
    nodes = api.get(dbase).json()["nodes"]
    dtrigger = next(n for n in nodes if n["kind"] == "trigger")
    output = next(n for n in nodes if n["kind"] == "output")
    timer = _post(api, f"{dbase}/nodes", kind="timer", seconds=30)
    _post(
        api,
        f"{dbase}/edges",
        source_id=dtrigger["id"],
        source_port="out",
        target_id=timer["id"],
        target_port="in",
    )
    _post(
        api,
        f"{dbase}/edges",
        source_id=timer["id"],
        source_port="out",
        target_id=output["id"],
        target_port="pass",
    )
    api.patch(
        f"{base}/nodes/{action['id']}", json={"definition_id": definition["id"]}
    ).raise_for_status()
    return pipeline


def test_start_and_stop_in_the_dialog_and_the_artifact_is_locked_while_it_runs(
    board: Board, api: httpx.Client
) -> None:
    _slow_pipeline(api)
    task = board.create("Item")
    board.open()
    dialog = board.open_card("Item")
    run = dialog.root.locator('[data-card-action="run"]')
    expect(run).to_contain_text("Start processing")
    expect(dialog.rail("pipeline")).to_contain_text("Flow")
    expect(dialog.rail("stage")).to_contain_text("Gap analysis")

    run.click()
    expect(run).to_contain_text("Stop processing")
    expect(dialog.rail("lane")).to_have_attribute("aria-disabled", "true")
    expect(dialog.rail("stage")).to_have_attribute("aria-disabled", "true")
    expect(board.card("Item").locator(".task-card__run")).to_contain_text("Gap analysis · running")
    assert api.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).status_code == 409

    run.click()
    expect(run).to_contain_text("Start processing")
    expect(dialog.rail("lane")).to_have_attribute("aria-disabled", "false")
    expect(board.card("Item").locator(".task-card__run")).to_contain_text("stopped")
    assert api.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).status_code == 200


def test_the_buttons_stay_where_they_are_when_the_dialog_switches_to_editing(
    board: Board, api: httpx.Client
) -> None:
    _slow_pipeline(api)
    board.create("Item")
    board.open()
    dialog = board.open_card("Item")
    close = dialog.root.locator("[data-modal-close]").last.bounding_box()
    edit = dialog.root.locator("[data-view-edit]")
    before = edit.bounding_box()
    dialog.edit()
    dialog.settle()
    save = dialog.root.locator("[data-submit]").bounding_box()
    assert close is not None and before is not None and save is not None
    assert abs(save["y"] - before["y"]) < 2  # Save sits where Edit was

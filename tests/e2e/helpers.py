"""Page object and API helpers shared by the browser tests."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.helpers import (
    build_definition,
    build_pipeline,
    connect,
    graph_url,
    kind_of,
    link,
    node,
    slow_pipeline,
)


def eventually(
    read: Callable[[], Any], expected: Any, timeout: float = 5.0, page: Page | None = None
) -> None:
    """`read()` becomes `expected` (server-side effects are asynchronous).

    Without `page` it polls with a plain sleep. Give the `page` when the test holds requests in a route
    handler: only a Playwright call lets the handler run, so the poll pauses through the page.
    """
    deadline = time.monotonic() + timeout
    while read() != expected:
        if time.monotonic() > deadline:
            raise AssertionError(f"expected {expected!r}, got {read()!r}")
        if page is None:
            time.sleep(0.02)
        else:
            page.wait_for_timeout(20)


def centre(locator: Locator) -> tuple[float, float]:
    """The middle of an element in page coordinates."""
    locator.wait_for(
        state="visible"
    )  # a slow machine draws it later than the click that precedes this
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag(page: Page, source: Locator, target: Locator, steps: int = 10) -> None:
    """Drag from the middle of `source` to the middle of `target` and release."""
    sx, sy = centre(source)
    tx, ty = centre(target)
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(tx, ty, steps=steps)
    page.mouse.up()


class Board:
    """The Kanban page: lookups, a few compound actions and the REST client for set-up."""

    def __init__(self, page: Page, base_url: str, api: httpx.Client) -> None:
        self.page = page
        self.base_url = base_url
        self.api = api

    # ── set-up through the API ───────────────────────────────────────

    def create(self, title: str, status: str = "backlog", **fields: Any) -> dict[str, Any]:
        """Create an artifact over REST (not through the UI); `parent_id` is set right after."""
        parent_id = fields.pop("parent_id", None)
        response = self.api.post("/api/tasks", json={"title": title, "status": status, **fields})
        response.raise_for_status()
        task: dict[str, Any] = response.json()
        if parent_id:
            self.patch(task, parent_id=parent_id)
            task["parent_id"] = parent_id
        return task

    def stored(self) -> dict[str, dict[str, Any]]:
        """All artifacts by title, as the server has them."""
        return {t["title"]: t for t in self.api.get("/api/tasks").json()}

    def stored_titles(self, status: str) -> list[str]:
        """Titles of a lane in server order."""
        return [t["title"] for t in self.api.get("/api/tasks").json() if t["status"] == status]

    def expect_titles(self, status: str, titles: list[str]) -> None:
        """The server order of a lane becomes `titles` (requests are asynchronous: polls)."""
        self._eventually(lambda: self.stored_titles(status), titles)

    def expect_field(self, title: str, field: str, value: Any) -> None:
        """A stored field of an artifact becomes `value` (polls)."""
        self._eventually(lambda: self.stored().get(title, {}).get(field), value)

    @staticmethod
    def _eventually(read: Callable[[], Any], expected: Any, timeout: float = 5.0) -> None:
        eventually(read, expected, timeout)

    def patch(self, task: dict[str, Any], **fields: Any) -> None:
        """Change an artifact over REST, as another client would."""
        self.api.patch(f"/api/tasks/{task['id']}", json=fields).raise_for_status()

    # ── page ──────────────────────────────────────────────────────────

    def open(self) -> Board:
        """Load the board and wait until it has rendered."""
        self.page.goto(self.base_url)
        expect(self.page.locator(".lane")).to_have_count(3)
        self.page.evaluate("localStorage.clear()")
        return self

    def open_with_lanes(self, count: int) -> Board:
        """Load the board when lanes were added or deleted over REST, and wait for them."""
        self.page.goto(self.base_url)
        expect(self.page.locator(".lane")).to_have_count(count)
        return self

    def lane(self, status: str) -> Locator:
        return self.page.locator(f'[data-lane][data-status="{status}"]')

    def card(self, title: str) -> Locator:
        """A card on the board (the lane settings dialog has sample cards of its own)."""
        return self.page.locator(".board .task-card").filter(
            has=self.page.locator(".task-card__title", has_text=title)
        )

    def titles(self, status: str) -> list[str]:
        """Card titles of a lane as shown, top to bottom."""
        return self.lane(status).locator(".task-card__title").all_inner_texts()

    def open_card(self, title: str) -> Dialog:
        self.card(title).locator(".task-card__title").click()
        dialog = Dialog(self.page)
        expect(dialog.root).to_be_visible()
        dialog.settle()
        return dialog

    def drag(
        self, source: Locator, target: Locator, *, edge: str = "center", release: bool = True
    ) -> None:
        """Drag with the mouse; `edge` is where on the target to drop: top, bottom or center."""
        a = source.bounding_box()
        b = target.bounding_box()
        assert a is not None and b is not None
        x = b["x"] + b["width"] / 2
        y = {"top": b["y"] + 5, "bottom": b["y"] + b["height"] - 5}.get(
            edge, b["y"] + b["height"] / 2
        )
        mouse = self.page.mouse
        mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
        mouse.down()
        mouse.move(x, y, steps=12)
        if release:
            mouse.up()


class Dialog:
    """The artifact dialog (create, view and edit mode)."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.root = page.locator("#create-task-modal")
        self.heading = self.root.locator(".modal__title")
        self.title_input = self.root.locator("#create-task-modal-field-title")
        self.body_input = self.root.locator("#create-task-modal-field-body")
        self.view = self.root.locator("[data-task-view]")
        self.view_title = self.root.locator("[data-view-title]")
        self.view_body = self.root.locator("[data-view-body]")
        self.number = self.root.locator("[data-modal-number]")
        self.lane_chip = self.root.locator("[data-modal-subtitle]")
        self.rail_toggle = self.root.locator("[data-card-nav-toggle]")

    def settle(self) -> None:
        """Wait until opening and resizing animations are over, so positions can be compared."""
        self.page.evaluate(
            "Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {})))"
        )

    def rail(self, field: str) -> Locator:
        return self.root.locator(f'[data-card-field="{field}"]')

    def option(self, name: str) -> Locator:
        """An entry of the open picker popover."""
        return self.root.locator(".popover:not([hidden]) [role=option]").filter(
            has_text=re.compile(f"^{re.escape(name)}$")
        )

    def edit(self) -> Dialog:
        self.root.locator("[data-view-edit]").click()
        return self

    def save(self) -> None:
        self.root.locator("[data-submit]").click()

    # ── tabs and the History tab ────────────────────────────────────────

    def tab(self, name: str) -> Locator:
        return self.root.locator(f'[role="tab"][data-tab="{name}"]')

    @property
    def tabs(self) -> Locator:
        return self.root.locator('[role="tab"]')

    @property
    def history(self) -> Locator:
        return self.root.locator("[data-history]")

    @property
    def rows(self) -> Locator:
        return self.history.locator(".history-row")

    def row(self, number: int) -> Locator:
        return self.rows.filter(has=self.page.locator("[data-row-number]", has_text=f"#{number}"))

    @property
    def detail(self) -> Locator:
        return self.history.locator("[data-history-detail]")

    def open_history(self) -> Dialog:
        self.tab("history").click()
        expect(self.history).to_be_visible()
        return self

    def size(self) -> tuple[float, float]:
        box = self.root.locator(".modal__panel").bounding_box()
        assert box is not None
        return box["width"], box["height"]


def echo_pipeline(client: httpx.Client, text: str = "hello from echo") -> dict[str, Any]:
    """A pipeline with one stage whose action runs a Python Code node printing ``text``."""
    pipeline = build_pipeline(client, stages=1, name="Echo flow", stage_name="Echo stage")
    definition = build_definition(client, "Echo", output=None, fail_enabled=True)
    trigger, output = kind_of(client, definition, "trigger"), kind_of(client, definition, "output")
    code = node(
        client,
        definition,
        "code",
        name="echo",
        config={"language": "python", "code": f"print({text!r})"},
    )
    connect(client, definition, trigger, "out", code, "in")
    connect(client, definition, code, "pass", output, "pass")
    connect(client, definition, code, "fail", output, "fail")
    link(client, pipeline, pipeline["stages"][0][1], definition)
    return pipeline


def start(client: httpx.Client, task: dict[str, Any], pipeline: dict[str, Any]) -> None:
    """Start the artifact in the pipeline over the API."""
    response = client.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert response.status_code in (200, 201), response.text


def executions(client: httpx.Client, task: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = client.get(f"/api/tasks/{task['id']}/executions").json()["items"]
    return items


def wait_executions(client: httpx.Client, task: dict[str, Any], statuses: list[str]) -> None:
    """The statuses of the artifact's executions (newest first) become `statuses` (polls)."""
    Board._eventually(lambda: [e["status"] for e in executions(client, task)], statuses, 15)


# ── flows of an execution ────────────────────────────────────────────


def arrange(client: httpx.Client, graph: dict[str, Any]) -> None:
    """Lay the top-level nodes of a graph out left to right (the builders create them all at 0, 0)."""
    nodes = client.get(graph_url(graph)).json()["nodes"]
    order = ["trigger", "stage", "timer", "code", "http", "pipeline", "complete", "output"]
    line = sorted((n for n in nodes if n["stage_id"] is None), key=lambda n: order.index(n["kind"]))
    x = 40.0
    for n in line:
        wide = {"stage": 400, "code": 290, "output": 0}.get(n["kind"], 240)
        y = 40 if n["kind"] in ("stage", "output", "code") else 110
        client.patch(
            f"{graph_url(graph)}/nodes/{n['id']}", json={"x": x, "y": y}
        ).raise_for_status()
        x += wide


def code_definition(
    client: httpx.Client, name: str, code: str, node_name: str | None = None
) -> dict[str, Any]:
    """An action definition: trigger -> a Python Code node -> Output (On Pass and On Fail)."""
    definition = build_definition(client, name, output=None, fail_enabled=True)
    trigger, output = kind_of(client, definition, "trigger"), kind_of(client, definition, "output")
    step = node(
        client,
        definition,
        "code",
        name=node_name or name.lower(),
        config={"language": "python", "code": code},
    )
    connect(client, definition, trigger, "out", step, "in")
    connect(client, definition, step, "pass", output, "pass")
    connect(client, definition, step, "fail", output, "fail")
    arrange(client, definition)
    return definition


def two_stage_pipeline(client: httpx.Client) -> dict[str, Any]:
    """Stage "Build" runs the definition "Compile", stage "Ship" runs "Deliver" (both print a line)."""
    pipeline = build_pipeline(client, stages=2, name="Release flow", stage_name="Stage {}")
    for (stage, action), (stage_name, definition_name) in zip(
        pipeline["stages"], [("Build", "Compile"), ("Ship", "Deliver")], strict=True
    ):
        client.patch(f"{graph_url(pipeline)}/nodes/{stage['id']}", json={"name": stage_name})
        link(
            client,
            pipeline,
            action,
            code_definition(client, definition_name, f"print('{definition_name} done')"),
        )
    arrange(client, pipeline)
    return pipeline


def failing_pipeline(client: httpx.Client) -> dict[str, Any]:
    """One action whose Code node exits with 1; its On Error leads to the end of the stage, so the
    execution still ends "done"."""
    pipeline = build_pipeline(client, stages=1, name="Failing flow", stage_name="Check")
    stage, action = pipeline["stages"][0]
    link(
        client,
        pipeline,
        action,
        code_definition(client, "Verify", "import sys\nprint('broken')\nsys.exit(1)"),
    )
    connect(client, pipeline, action, "error", stage, "end")
    arrange(client, pipeline)
    return pipeline


def ending_in_failure(client: httpx.Client) -> dict[str, Any]:
    """A pipeline whose action ends in On Fail, so the execution ends ``failed``."""
    pipeline = build_pipeline(client, stages=1, name="Failing build", stage_name="Check")
    definition = build_definition(client, "Fails", output="fail", fail_enabled=True)
    link(client, pipeline, pipeline["stages"][0][1], definition)
    return pipeline


def nested_pipeline(client: httpx.Client) -> tuple[dict[str, Any], dict[str, Any]]:
    """An outer pipeline that calls an inner one (one stage, one Code action). Returns (outer, inner)."""
    inner = build_pipeline(client, stages=1, name="Inner flow", stage_name="Inner stage")
    link(client, inner, inner["stages"][0][1], code_definition(client, "Inner work", "print('in')"))
    outer = build_pipeline(client, stages=1, name="Outer flow", stage_name="Outer stage")
    complete = kind_of(client, outer, "complete")
    call = node(client, outer, "pipeline")
    connect(client, outer, outer["stages"][0][0], "end", call, "in")
    connect(client, outer, call, "out", complete, "in")
    response = client.patch(
        f"{graph_url(outer)}/nodes/{call['id']}", json={"definition_id": inner["id"]}
    )
    assert response.status_code == 200, response.text
    arrange(client, inner)
    arrange(client, outer)
    return outer, inner


def retry_pipeline(client: httpx.Client, marker: str) -> dict[str, Any]:
    """One action that fails the first time it runs and passes the second: its On Error leads back
    to itself. ``marker`` is a path the Code node creates on the first run."""
    pipeline = build_pipeline(client, stages=1, name="Retry flow", stage_name="Flaky stage")
    action = pipeline["stages"][0][1]
    code = (
        "import os, sys\n"
        f"marker = {marker!r}\n"
        "if os.path.exists(marker):\n"
        "    print('second try')\n"
        "else:\n"
        "    open(marker, 'w').close()\n"
        "    print('first try')\n"
        "    sys.exit(1)\n"
    )
    link(client, pipeline, action, code_definition(client, "Flaky", code))
    connect(client, pipeline, action, "error", action, "in")
    arrange(client, pipeline)
    return pipeline


def slow_flow(client: httpx.Client, seconds: int = 4) -> dict[str, Any]:
    """A pipeline whose action first prints, then waits (a timer): a run that stays running a while."""
    pipeline = slow_pipeline(client, seconds=seconds, stage_name="Waiting stage")
    arrange(client, pipeline)
    return pipeline


def execution_of(client: httpx.Client, task: dict[str, Any], number: int = 1) -> dict[str, Any]:
    """The execution of the artifact with this number."""
    return next(e for e in executions(client, task) if e["number"] == number)


def flow_url(base_url: str, task: dict[str, Any], execution: dict[str, Any]) -> str:
    """The page of the flow of an execution."""
    return f"{base_url}/artifacts/{task['number']}/executions/{execution['id']}"


def run_started(
    client: httpx.Client, task: dict[str, Any], pipeline: dict[str, Any], **at: Any
) -> None:
    """Start the artifact (optionally at a stage or an action) and wait until it is no longer running."""
    response = client.post(
        f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"], **at}
    )
    assert response.status_code in (200, 201), response.text
    Board._eventually(
        lambda: all(e["status"] != "running" for e in executions(client, task)), True, 20
    )


def pick_node(page: Page, kind: str) -> None:
    """Add a node from the open add menu by searching for its kind (the clusters are closed until opened)."""
    page.fill(".ge-add__search", kind)
    page.click(f"[data-add={kind}]")


def menu_kinds(page: Page) -> dict[str, list[str]]:
    """The open add menu: each cluster with the names of its kinds (opens the clusters one after the other)."""
    kinds: dict[str, list[str]] = {}
    for group in page.locator("[data-add-list] [data-group]").all():
        name = group.get_attribute("data-group") or ""
        group.click()
        kinds[name] = [
            t.split("\n")[0]
            for t in page.locator("[data-add-list] [data-add] span:first-child").all_inner_texts()
        ]
    return kinds

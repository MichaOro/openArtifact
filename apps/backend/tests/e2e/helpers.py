"""Page object and API helpers shared by the browser tests."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

LANES = ("backlog", "in_progress", "done")


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
        deadline = time.monotonic() + timeout
        while read() != expected:
            if time.monotonic() > deadline:
                raise AssertionError(f"expected {expected!r}, the server has {read()!r}")
            time.sleep(0.05)

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

    def lane(self, status: str) -> Locator:
        return self.page.locator(f'[data-lane][data-status="{status}"]')

    def card(self, title: str) -> Locator:
        return self.page.locator(".task-card").filter(
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

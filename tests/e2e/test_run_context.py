"""The run context in the browser: an action whose first Code node sets a variable and whose second
reads it from ``context.json``; the History tab shows the context of the execution, read-only."""

from __future__ import annotations

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import Board, start, wait_executions
from tests.helpers import build_definition, build_pipeline, connect, kind_of, link, node

SETTER = "import json\nprint(json.dumps({'ok': True, 'vars': {'user': 'bob'}}))"
READER = "import json\nprint('saw', json.load(open('context.json'))['vars']['user'])"


def test_the_history_detail_shows_the_context_a_two_node_action_built(
    board: Board, api: httpx.Client, page: Page
) -> None:
    pipeline = build_pipeline(api, stages=1, name="Context flow")
    definition = build_definition(api, "Two nodes", output=None, fail_enabled=True)
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    first = node(
        api, definition, "code", name="Set user", config={"language": "python", "code": SETTER}
    )
    second = node(
        api, definition, "code", name="Read user", config={"language": "python", "code": READER}
    )
    connect(api, definition, trigger, "out", first, "in")
    connect(api, definition, first, "pass", second, "in")
    connect(api, definition, second, "pass", output, "pass")
    connect(api, definition, first, "fail", output, "fail")
    connect(api, definition, second, "fail", output, "fail")
    link(api, pipeline, pipeline["stages"][0][1], definition)
    task = board.create("Item")
    start(api, task, pipeline)
    wait_executions(api, task, ["done"])

    dialog = board.open().open_card("Item").open_history()
    dialog.row(1).locator(".history-row__open").click()
    block = dialog.detail.locator("[data-detail-context] details")
    expect(block.locator("summary")).to_have_text(
        "Run context (1 variable · 4 parameters · 2 node results)"
    )
    expect(block.locator("pre")).to_be_hidden()
    block.locator("summary").click()
    text = block.locator("pre")
    expect(text).to_be_visible()
    expect(text).to_contain_text('"user": "bob"')
    expect(text).to_contain_text('"Read_user"')
    expect(text).to_contain_text("saw bob")
    expect(block.get_by_role("button", name="Copy")).to_be_visible()

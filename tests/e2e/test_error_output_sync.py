"""The error output of an action is one state of its definition and its uses (ADR-061 addendum), seen in the editors."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import arrange, eventually, failure_setting
from tests.helpers import build_definition, build_pipeline, graph_url, kind_of, link

ACTION_SETTING = "If the action fails"


def _flag(api: httpx.Client, definition: dict[str, Any]) -> bool:
    return bool(kind_of(api, definition, "output")["fail_enabled"])


def _mode(api: httpx.Client, pipeline: dict[str, Any], node: dict[str, Any]) -> str:
    nodes = api.get(graph_url(pipeline)).json()["nodes"]
    return str(next(n for n in nodes if n["id"] == node["id"])["config"]["on_failure"])


def _pipeline_with_uses(
    api: httpx.Client, definition: dict[str, Any], count: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pipeline = build_pipeline(api, stages=count)
    uses = [action for _stage, action in pipeline["stages"]]
    for use in uses:
        link(api, pipeline, use, definition)
    arrange(api, pipeline)
    return pipeline, uses


def _open_settings(page: Page, action: Locator, entry: str = "Settings") -> Locator:
    action.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name=entry).click()
    return page.locator("#node-modal")


def _toggle_on_fail(
    page: Page, base_url: str, definition: dict[str, Any], api: httpx.Client
) -> None:
    arrange(api, definition)
    page.goto(f"{base_url}/actions/{definition['slug']}")
    output = page.locator(".ge-node--output")
    expect(output).to_be_visible()
    output.dblclick(position={"x": 30, "y": 5})
    page.locator("#node-modal").get_by_label("On Fail", exact=True).click()


def test_on_fail_in_the_definition_gives_the_use_its_error_output(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = build_definition(api, "Work")
    pipeline, uses = _pipeline_with_uses(api, definition, 1)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action .ge-port--pass")).to_be_visible()
    expect(
        page.locator(".ge-node--action .ge-port--error")
    ).to_be_hidden()  # the default: stop the run

    _toggle_on_fail(page, base_url, definition, api)
    eventually(lambda: _flag(api, definition), True)

    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action .ge-port--error")).to_be_visible()
    assert _mode(api, pipeline, uses[0]) == "error_output"


def test_the_error_output_of_a_use_gives_the_definition_its_on_fail_without_a_notice_when_alone(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = build_definition(api, "Work")
    pipeline, _uses = _pipeline_with_uses(api, definition, 1)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _open_settings(page, page.locator(".ge-node--action"))
    failure_setting(page, ACTION_SETTING).select_option(label="Error output")
    eventually(lambda: _flag(api, definition), True)
    expect(page.locator("[data-alert]")).to_be_hidden()  # nothing else is affected: nothing to say

    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-node--output .ge-port--fail")).to_be_visible()


def test_with_other_uses_the_notice_says_so_and_the_others_get_the_error_output_at_once(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = build_definition(api, "Work")
    pipeline, _uses = _pipeline_with_uses(api, definition, 3)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    actions = page.locator(".ge-node--action")
    expect(actions).to_have_count(3)
    _open_settings(page, actions.first)
    failure_setting(page, ACTION_SETTING).select_option(label="Error output")
    expect(page.locator("[data-alert]")).to_contain_text(
        "Also switched on in the action 'Work'; it applies to 2 other uses."
    )
    # the other two uses of this very pipeline changed too, and the editor shows it without a reload by hand
    expect(page.locator(".ge-node--action .ge-port--error")).to_have_count(3)


def test_switching_on_fail_off_disconnects_the_uses_and_says_how_many(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = build_definition(api, "Work", fail_enabled=True)
    pipeline, uses = _pipeline_with_uses(api, definition, 2)
    for (stage, _action), use in zip(pipeline["stages"], uses, strict=True):
        api.post(
            f"{graph_url(pipeline)}/edges",
            json={
                "source_id": use["id"],
                "source_port": "error",
                "target_id": stage["id"],
                "target_port": "end",
            },
        ).raise_for_status()

    _toggle_on_fail(page, base_url, definition, api)

    expect(page.locator("[data-alert]")).to_contain_text("Disconnected 2 connections")
    eventually(lambda: _flag(api, definition), False)
    edges = api.get(graph_url(pipeline)).json()["edges"]
    assert [e for e in edges if e["source_port"] == "error"] == []
    assert [_mode(api, pipeline, u) for u in uses] == ["fail", "fail"]


def test_a_node_leaving_the_error_output_is_disconnected_instead_of_refused(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """The old behaviour refused with "remove that connection first"; now the connection goes, said plainly."""
    definition = build_definition(api, "Check", output=None)
    trigger, output = kind_of(api, definition, "trigger"), kind_of(api, definition, "output")
    code = api.post(
        f"{graph_url(definition)}/nodes",
        json={"kind": "code", "config": {"code": "true", "on_failure": "error_output"}},
    ).json()
    for source, port, target, target_port in (
        (trigger, "out", code, "in"),
        (code, "pass", output, "pass"),
    ):
        api.post(
            f"{graph_url(definition)}/edges",
            json={
                "source_id": source["id"],
                "source_port": port,
                "target_id": target["id"],
                "target_port": target_port,
            },
        ).raise_for_status()
    api.patch(f"{graph_url(definition)}/nodes/{output['id']}", json={"fail_enabled": True})
    api.post(
        f"{graph_url(definition)}/edges",
        json={
            "source_id": code["id"],
            "source_port": "fail",
            "target_id": output["id"],
            "target_port": "fail",
        },
    ).raise_for_status()
    arrange(api, definition)
    page.goto(f"{base_url}/actions/{definition['slug']}")
    expect(page.locator(".ge-edge--fail")).to_have_count(1)

    page.locator(".ge-node--code").dblclick(position={"x": 30, "y": 5})
    failure_setting(page).select_option(label="Stop the run")

    expect(page.locator("[data-alert]")).to_contain_text("Disconnected 1 connection")
    expect(page.locator(".ge-edge--fail")).to_have_count(0)
    expect(page.locator(".ge-node--code .ge-port--fail")).to_be_hidden()


def test_an_open_editor_follows_a_definition_that_changes_in_another_tab(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = build_definition(api, "Work")
    pipeline, _uses = _pipeline_with_uses(api, definition, 1)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node--action .ge-port--pass")).to_be_visible()
    expect(page.locator(".ge-node--action .ge-port--error")).to_be_hidden()

    other = page.context.new_page()
    try:
        _toggle_on_fail(other, base_url, definition, api)
        eventually(lambda: _flag(api, definition), True)
        # the first page was not touched: the server's event made it load the graph again
        expect(page.locator(".ge-node--action .ge-port--error")).to_be_visible()
    finally:
        other.close()


def test_the_notice_speaks_german(page: Page, base_url: str, api: httpx.Client) -> None:
    page.context.add_cookies([{"name": "oa_lang", "value": "de", "url": base_url}])
    definition = build_definition(api, "Work")
    pipeline, _uses = _pipeline_with_uses(api, definition, 2)
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _open_settings(page, page.locator(".ge-node--action").first, "Einstellungen")
    failure_setting(page, "Wenn die Aktion fehlschlägt").select_option(label="Fehlerausgang")
    expect(page.locator("[data-alert]")).to_contain_text("gilt für 1 weitere Verwendung")

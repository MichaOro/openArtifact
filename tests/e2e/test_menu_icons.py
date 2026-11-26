"""Every entry of the "+" menus has the glyph of its kind (one column of icons, then the names), in the cluster list, in
the search result and in the "+" of a stage; the glyph is the manifest's, so a kind looks the same everywhere."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.helpers import node


def _pipeline(client: httpx.Client) -> dict[str, Any]:
    pipeline: dict[str, Any] = client.post("/api/pipelines", json={"name": "Glyphs"}).json()
    node(client, pipeline, "stage", name="Gap Analysis", x=240, y=40)
    return pipeline


def _definition(client: httpx.Client) -> dict[str, Any]:
    """An action definition: its editor offers the kinds that run (Code, HTTP, Timer, the tools ...)."""
    definition: dict[str, Any] = client.post("/api/actions", json={"name": "Glyph action"}).json()
    return definition


def _open(page: Page, base_url: str, slug: str, folder: str = "pipelines") -> None:
    page.goto(f"{base_url}/{folder}/{slug}")
    expect(page.locator(".ge-node").first).to_be_visible()


def _without_glyph(page: Page) -> list[str]:
    """The names of the entries that show no glyph before them."""
    names: list[str] = page.locator(".ge-add__item").evaluate_all(
        "items => items.filter(i => !i.querySelector('.ge-add__name > svg.icon')).map(i => i.textContent.trim())"
    )
    return names


def test_every_entry_of_the_add_menu_shows_a_glyph_in_every_cluster(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    definition = _definition(api)
    _open(page, base_url, definition["slug"], "actions")
    page.click("[data-add-menu]")
    seen = 0
    for name in page.locator(".ge-add__group").evaluate_all(
        "groups => groups.map(g => g.dataset.group)"
    ):
        group = page.locator(f'.ge-add__group[data-group="{name}"]')
        if group.get_attribute("aria-expanded") == "false":
            group.click()
        expect(group).to_have_attribute("aria-expanded", "true")
        seen += page.locator(".ge-add__item").count()
        assert _without_glyph(page) == [], "entries without a glyph in an open cluster"
    assert seen >= 12, "the clusters hold the kinds"


def test_the_search_result_keeps_the_glyphs(page: Page, base_url: str, api: httpx.Client) -> None:
    definition = _definition(api)
    _open(page, base_url, definition["slug"], "actions")
    page.click("[data-add-menu]")
    page.locator(".ge-add__search").fill("r")  # Timer, Artifact, Switch, Set ... contain an "r"
    assert page.locator(".ge-add__item").count() > 3
    assert _without_glyph(page) == []
    names = page.locator(".ge-add__item").all_inner_texts()
    assert any("Timer" in n for n in names) and any("Artifact" in n for n in names)


def test_the_menu_of_the_pipeline_editor_shows_glyphs_for_stage_pipeline_and_guard(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline["slug"])
    page.click("[data-add-menu]")
    page.locator('.ge-add__group[data-group="Structure"]').click()
    assert page.locator(".ge-add__name").all_inner_texts() == ["Stage", "Pipeline", "Guard"]
    assert _without_glyph(page) == []


def test_a_kind_has_the_glyph_its_manifest_names(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """Stage, Pipeline and Timer have no icon on their card: the manifest's ``menu_icon`` gives them theirs."""
    definition = _definition(api)
    _open(page, base_url, definition["slug"], "actions")
    kinds = {k["kind"]: k["menu_icon"] for k in api.get("/api/node-types").json()}
    assert (kinds["stage"], kinds["pipeline"], kinds["timer"]) == ("layers", "pipeline", "clock")
    page.click("[data-add-menu]")
    page.locator(".ge-add__search").fill("Timer")
    shown = page.locator('.ge-add__item[data-add="timer"] svg.icon').first.inner_html()
    wanted = page.evaluate(
        "() => document.querySelector('#icons').content.querySelector('[data-icon=\"clock\"] > svg').innerHTML"
    )
    assert shown == wanted


def test_the_menu_of_a_stage_shows_the_glyph_of_an_action_and_the_guard_glyph(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _pipeline(api)
    _open(page, base_url, pipeline["slug"])
    page.locator(".ge-stage__add").click()
    entries = page.locator('.menu:not([hidden]) [role="menuitem"]')
    expect(entries).to_have_count(2)
    for index in range(2):
        assert entries.nth(index).locator("svg.icon").count() == 1, entries.nth(index).inner_text()

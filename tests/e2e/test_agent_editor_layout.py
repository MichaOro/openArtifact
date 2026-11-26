"""The agent editor's two layout rules (card #110): a long list of versions folds its middle (the newest two and the first stay behind
"Show more versions (N)"), and a row of inputs shows every choice in full and breaks in pairs when the table gets narrow."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_agents import _agent, _tab, agents_url, api, llm, signed_in

__all__ = ["agents_url", "api", "llm", "signed_in"]


def _agent_with_versions(api: httpx.Client, versions: int) -> dict[str, Any]:
    agent = _agent(api)
    for number in range(2, versions + 1):
        api.put(
            f"/api/agents/{agent['id']}/draft",
            json={**agent["draft"], "temperature": round(0.2 + number / 20, 2)},
        ).raise_for_status()
        api.post(f"/api/agents/{agent['id']}/publish").raise_for_status()
    return agent


def _editor(page: Page, agents_url: str, agent: dict[str, Any]) -> Locator:
    page.goto(f"{agents_url}/agents/{agent['id']}")
    return page.locator("main, body").first


def test_seven_versions_show_the_newest_two_and_the_first_and_fold_the_four_between(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = _agent_with_versions(api, 7)
    page = signed_in
    editor = _editor(page, agents_url, agent)
    _tab(editor, "Versions & use")
    rows = editor.locator("[data-versions] .ag-version")
    separator = editor.locator("[data-versions] .fold-separator__button")
    expect(rows).to_have_count(3)
    expect(rows.locator("strong")).to_have_text(["Version 7", "Version 6", "Version 1"])
    expect(separator).to_have_text("Show more versions (4)")
    expect(separator).to_have_attribute("aria-expanded", "false")
    # the separator sits between the newest two and the first, with a line through its middle
    order = editor.locator("[data-versions] > li").evaluate_all(
        "els => els.map(e => e.classList.contains('fold-separator') ? 'fold' : 'version')"
    )
    assert order == ["version", "version", "fold", "version"]
    # opened (with the keyboard): the four hidden ones are there and can be used like the others
    separator.focus()
    page.keyboard.press("Enter")
    expect(rows).to_have_count(7)
    expect(rows.locator("strong")).to_have_text([f"Version {n}" for n in (7, 6, 5, 4, 3, 2, 1)])
    expect(editor.locator("[data-versions] .fold-separator__button")).to_have_text(
        "Hide 4 versions"
    )
    expect(editor.locator("[data-versions] .fold-separator__button")).to_have_attribute(
        "aria-expanded", "true"
    )
    editor.get_by_label("Show version 4").click()
    expect(page.locator("#version-modal")).to_be_visible()
    page.keyboard.press("Escape")
    # closed again
    editor.locator("[data-versions] .fold-separator__button").click()
    expect(rows).to_have_count(3)


def test_three_versions_are_listed_as_they_are(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = _agent_with_versions(api, 3)
    editor = _editor(signed_in, agents_url, agent)
    _tab(editor, "Versions & use")
    expect(editor.locator("[data-versions] .ag-version")).to_have_count(3)
    expect(editor.locator("[data-versions] .fold-separator")).to_have_count(0)


def _cut(select: Locator) -> bool:
    """Whether the widest choice of the select needs more room than the select has (its text would be cut)."""
    return bool(
        select.evaluate(
            """el => {
                const c = document.createElement('canvas').getContext('2d'); const s = getComputedStyle(el);
                c.font = s.font;
                const need = Math.max(...[...el.options].map(o => c.measureText(o.text).width))
                    + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight);
                return need > el.getBoundingClientRect().width + 0.5;
            }"""
        )
    )


def test_the_inputs_show_every_choice_in_full_and_break_in_pairs_when_the_table_gets_narrow(
    signed_in: Page, agents_url: str, api: httpx.Client
) -> None:
    agent = _agent(
        api,
        user_prompt="Summarise: ${input.text}",
        inputs=[{"name": "text", "source": "artifact", "part": "title_body"}],
    )
    page = signed_in
    # wide: one line of six; narrower: pairs (2, 2, 2); narrowest: one column (a pair would cut a choice)
    for width, columns in ((1500, 6), (900, 2), (700, 1)):
        page.set_viewport_size({"width": width, "height": 900})
        editor = _editor(page, agents_url, agent)
        _tab(editor, "Inputs")
        row = editor.locator("[data-inputs] .ag-input").first
        expect(row).to_be_visible()
        for key in ("source", "type", "required"):
            assert not _cut(row.locator(f'select[data-input="{key}"]')), f"{key} at {width} px"
        tracks = row.evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length")
        assert tracks == columns, f"{tracks} columns at {width} px"

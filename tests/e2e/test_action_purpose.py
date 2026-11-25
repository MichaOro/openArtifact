"""An action is made for pipelines or for guards (ADR-067): the window that makes it asks for the type, the list keeps the two apart
(two tabs, a Guard chip next to Draft), a type that is in use on the other side cannot change (the window says where), a stage offers
only the actions for pipelines, and the "+" menu of a guard action offers the nodes for guards."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.helpers import eventually, pick_node
from tests.helpers import build_pipeline, graph_url, link

_PURPOSES = {"pipeline": "For pipelines", "guard": "For guards"}


def _make(page: Page, name: str, purpose: str) -> None:
    page.click("[data-new-graph]")
    dialog = page.locator("#graph-modal")
    expect(dialog).to_be_visible()
    dialog.get_by_label("Name").fill(name)
    dialog.locator(f'[data-choice="{purpose}"]').click()
    dialog.locator("[data-submit]").click()
    expect(page).to_have_url(re.compile(r"/actions/[a-z0-9-]+$"))


def test_an_action_is_made_for_guards_listed_apart_and_changed_with_protection(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/actions")
    page.click("[data-new-graph]")
    dialog = page.locator("#graph-modal")
    expect(dialog.locator('[data-choice="pipeline"]')).to_have_attribute(
        "aria-pressed", "true"
    )  # the default
    expect(dialog.get_by_text("For guards")).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    _make(page, "Judge", "guard")
    assert [a["purpose"] for a in api.get("/api/actions").json()] == ["guard"]
    page.goto(f"{base_url}/actions")
    # two tabs: the one for pipelines is open and empty, the guard actions are in the other with the Guard chip next to Draft
    expect(page.locator(".mg__empty")).to_be_visible()
    page.get_by_role("tab", name=re.compile("Guard actions")).click()
    item = page.locator(".mg-card")
    expect(item).to_have_count(1)
    expect(item.locator(".mg-chip")).to_have_text(["Guard", "Draft"])
    # Properties (in the panel of the selected entry) change name and type in the same window
    item.click()
    page.locator("[data-properties]").click()
    expect(dialog.locator("#graph-modal-title, .modal__title")).to_have_text("Edit action")
    dialog.locator('[data-choice="pipeline"]').click()
    dialog.locator("[data-submit]").click()
    eventually(lambda: api.get("/api/actions").json()[0]["purpose"], "pipeline", page=page)
    page.get_by_role("tab", name=re.compile("Pipeline actions")).click()
    pipeline_item = page.locator(".mg-card")
    expect(pipeline_item).to_have_count(1)
    expect(pipeline_item.locator(".mg-chip")).to_have_text(["Pipeline", "Draft"])
    # an action a stage uses cannot become a guard action: the window says where
    flow = build_pipeline(api, name="Uses Judge", stages=1)
    (action,) = api.get("/api/actions").json()
    link(api, flow, flow["stages"][0][1], action)
    page.reload()
    page.locator(".mg-card").click()
    page.locator("[data-properties]").click()
    dialog.locator('[data-choice="guard"]').click()
    dialog.locator("[data-submit]").click()
    expect(dialog.locator("[data-form-error]")).to_contain_text(
        "used by the stages of 'Uses Judge'"
    )
    assert api.get(graph_url(action)).json()["graph"]["purpose"] == "pipeline"


def test_a_stage_offers_only_the_actions_for_pipelines(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    api.post("/api/actions", json={"name": "Plain"}).raise_for_status()
    api.post("/api/actions", json={"name": "Judge", "purpose": "guard"}).raise_for_status()
    flow = build_pipeline(api, name="Flow", stages=1)
    page.goto(f"{base_url}/pipelines/{flow['slug']}")
    page.locator(".ge-node--action").first.locator(".ge-node__name").dblclick()
    select = page.locator(".ge-inspector select[data-focus-key='link']")
    expect(select.locator("option")).to_have_text(["Not defined", "Plain"])


def test_the_plus_menu_of_a_guard_action_and_a_pipeline_action_offers_what_their_kinds_allow(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    judge = api.post("/api/actions", json={"name": "Judge", "purpose": "guard"}).json()
    plain = api.post("/api/actions", json={"name": "Plain"}).json()
    for definition in (judge, plain):
        page.goto(f"{base_url}/actions/{definition['slug']}")
        expect(page.locator(".ge-node--output")).to_be_visible()
        page.click("[data-add-menu]")
        pick_node(page, "code")
        expect(page.locator(".ge-node--code")).to_have_count(
            1
        )  # a kind that is for both is in both


def test_the_sqlite_node_is_offered_only_in_a_guard_action_and_is_set_up_like_the_postgres_node(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    judge = api.post("/api/actions", json={"name": "Judge", "purpose": "guard"}).json()
    plain = api.post("/api/actions", json={"name": "Plain"}).json()
    page.goto(f"{base_url}/actions/{plain['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "sqlite")
    expect(page.locator("[data-add=sqlite]")).to_have_count(
        0
    )  # a pipeline action does not offer it
    expect(page.locator("[data-add=sqlite_tool]")).to_have_count(0)
    page.goto(f"{base_url}/actions/{judge['slug']}")
    expect(page.locator(".ge-node--output")).to_be_visible()
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "sqlite")
    expect(page.locator("[data-add=sqlite_tool]")).to_have_count(1)
    page.click("[data-add=sqlite]")
    card = page.locator(".ge-node--sqlite")
    expect(card).to_have_count(1)
    card.dblclick(position={"x": 30, "y": 5})
    dialog = page.locator("#node-modal")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Data source")).to_have_value("app")
    query = dialog.get_by_label("Query", exact=True)
    query.fill("SELECT lane, count(*) FROM v_guard_artifacts GROUP BY lane")
    dialog.get_by_label(
        "Data source"
    ).focus()  # leaving the field saves it (a code field keeps Tab for indenting)
    eventually(
        lambda: next(
            n["config"].get("query")
            for n in api.get(graph_url(judge)).json()["nodes"]
            if n["kind"] == "sqlite"
        ),
        "SELECT lane, count(*) FROM v_guard_artifacts GROUP BY lane",
        page=page,
    )
    # the same menu group as Postgres, and the blocked tables are an optional setting
    page.keyboard.press("Escape")
    page.click("[data-add-menu]")
    page.fill(".ge-add__search", "postgres")
    expect(page.locator("[data-add=postgres]")).to_have_count(1)


def _chips(dialog):  # type: ignore[no-untyped-def]
    return {
        purpose: dialog.locator(f'[data-choice="{purpose}"]') for purpose in ("pipeline", "guard")
    }


def _outlined(chip) -> bool:  # type: ignore[no-untyped-def]
    """The chip has a visible frame: a width and a colour that is not transparent."""
    width, colour = chip.evaluate(
        "el => { const s = getComputedStyle(el); return [parseFloat(s.borderTopWidth), s.borderTopColor]; }"
    )
    return bool(width > 0 and colour not in ("rgba(0, 0, 0, 0)", "transparent"))


def test_the_chosen_type_is_marked_with_a_tint_and_a_frame_and_it_is_the_type_that_is_made(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    page.goto(f"{base_url}/actions")
    page.click("[data-new-graph]")
    dialog = page.locator("#graph-modal")
    expect(dialog).to_be_visible()
    chips = _chips(dialog)
    for chosen, other in (("guard", "pipeline"), ("pipeline", "guard"), ("guard", "pipeline")):
        chips[chosen].click()
        expect(chips[chosen]).to_have_attribute("aria-pressed", "true")
        expect(chips[other]).to_have_attribute("aria-pressed", "false")
        page.mouse.move(5, 5)  # not hovered, not the pointer: the marking itself
        assert _outlined(chips[chosen]), f"the chosen chip ({chosen}) keeps its frame"
        tinted = chips[chosen].evaluate("el => getComputedStyle(el).backgroundColor")
        plain = chips[other].evaluate("el => getComputedStyle(el).backgroundColor")
        assert tinted != plain, "the chosen chip is tinted"
    dialog.get_by_label("Name").fill("Gate")
    dialog.locator("[data-submit]").click()
    expect(page).to_have_url(re.compile(r"/actions/[a-z0-9-]+$"))
    assert [a["purpose"] for a in api.get("/api/actions").json()] == ["guard"]

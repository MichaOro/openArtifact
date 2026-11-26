"""The management pages of pipelines and actions (ADR-069): a click selects and shows the details in the panel, a double click and the
pencil open the editor, the bin deletes after a question, the keys move and open, cards or list, search and tags, the usage tab,
the versions tab, and the sheet on a narrow screen."""

from __future__ import annotations

import re
from typing import cast

import httpx
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import eventually
from tests.helpers import build_pipeline, connect, graph_url, link, node, post


def _card(page: Page, name: str):  # type: ignore[no-untyped-def]
    return page.locator(".mg-card", has_text=name)


def test_a_click_selects_and_shows_the_panel_a_double_click_and_the_pencil_open_the_editor(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/actions", name="Gap analysis", description="Finds gaps.", tags=["epic"])
    page.goto(f"{base_url}/actions")
    panel = page.locator(".mg__panel")
    expect(panel).to_contain_text(
        "Select an action to see its details"
    )  # the room is reserved, a quiet line stands in it
    expect(panel.locator("h2")).to_have_count(0)
    _card(page, "Gap analysis").click()
    expect(panel).to_be_visible()
    expect(panel.locator("h2")).to_have_text("Gap analysis")
    expect(_card(page, "Gap analysis")).to_have_attribute("aria-current", "true")
    expect(panel.get_by_role("tab")).to_have_text(["Overview", "Graph", "Versions", "Usage"])
    expect(
        panel.get_by_role("tab", name="Versions")
    ).to_be_enabled()  # pipelines and actions have versions now (ADR-070)
    expect(panel.locator(".mg-tag")).to_have_text(["epic"])
    _card(page, "Gap analysis").dblclick()
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")
    page.go_back()
    _card(page, "Gap analysis").locator("[data-edit]").click()
    expect(page).to_have_url(f"{base_url}/actions/gap-analysis")


def test_the_keys_select_open_and_delete_and_the_bin_asks_first(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/pipelines", name="Alpha")
    post(api, "/api/pipelines", name="Beta")
    page.goto(f"{base_url}/pipelines")
    page.locator("#graph-modal").wait_for(state="attached")
    page.get_by_label("Order").select_option("name")
    first = page.locator(".mg-card").first
    first.focus()
    page.keyboard.press("ArrowDown")
    expect(_card(page, "Beta")).to_have_attribute("aria-current", "true")
    expect(page.locator(".mg__panel h2")).to_have_text("Beta")
    page.keyboard.press("Delete")
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.keyboard.press("Escape")
    assert len(api.get("/api/pipelines").json()) == 2, (
        "asked first, nothing is deleted without the answer"
    )
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{base_url}/pipelines/beta")
    page.go_back()
    _card(page, "Beta").locator("[data-delete]").click()
    page.click("#confirm-modal [data-confirm]")
    expect(page.locator(".mg-card")).to_have_count(1)
    eventually(lambda: [p["name"] for p in api.get("/api/pipelines").json()], ["Alpha"], page=page)


def test_cards_or_list_search_and_tags_and_the_usage_of_an_action(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    judge = post(api, "/api/actions", name="Judge", tags=["review"])
    post(api, "/api/actions", name="Mailer", tags=["mail"])
    flow = build_pipeline(api, name="Review flow", stages=1, stage_name="Check")
    link(api, flow, flow["stages"][0][1], judge)
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg__list")).to_have_attribute("data-view", "cards")
    page.get_by_role("button", name="List").click()
    expect(page.locator(".mg__list")).to_have_attribute("data-view", "list")
    page.reload()
    expect(page.locator(".mg__list")).to_have_attribute(
        "data-view", "list"
    )  # kept for the next visit
    page.get_by_role("searchbox").fill("mail")
    expect(page.locator(".mg-card")).to_have_count(1)
    page.get_by_role("searchbox").fill("review")  # a tag is searched too
    expect(_card(page, "Judge")).to_have_count(1)
    page.get_by_role("searchbox").fill("")
    page.get_by_role("button", name="Filter").click()
    page.get_by_role("menuitem", name="mail").click()
    expect(page.locator(".mg-card")).to_have_count(1)
    expect(_card(page, "Mailer")).to_be_visible()
    page.get_by_role("button", name="Filter").click()
    page.get_by_role("menuitem", name="All tags").click()
    _card(page, "Judge").click()
    page.locator(".mg__panel").get_by_role("tab", name="Usage").click()
    link_to_flow = page.locator(".mg__panel .mg-uses a")
    expect(link_to_flow).to_have_text("Review flow · Check")
    expect(link_to_flow).to_have_attribute("href", "/pipelines/review-flow")


def test_a_new_pipeline_gets_description_and_tags_and_the_panel_is_a_sheet_on_a_narrow_screen(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/pipelines", name="Existing")
    page.goto(f"{base_url}/pipelines")
    page.click("[data-new-graph]")
    window = page.locator("#graph-modal")
    window.get_by_label("Name").fill("Described")
    window.get_by_label("Description").fill("Does things.")
    window.get_by_label("Tags").fill("epic, Epic, analysis")
    window.locator("[data-submit]").click()
    expect(page).to_have_url(f"{base_url}/pipelines/described")
    made = next(p for p in api.get("/api/pipelines").json() if p["name"] == "Described")
    assert (made["description"], made["tags"]) == ("Does things.", ["epic", "analysis"])
    page.set_viewport_size({"width": 420, "height": 850})
    page.goto(f"{base_url}/pipelines")
    _card(page, "Existing").click()
    panel = page.locator(".mg__panel")
    expect(panel).to_be_visible()
    assert panel.evaluate("el => getComputedStyle(el).position") == "fixed", (
        "a sheet from the bottom"
    )
    box = panel.bounding_box()
    assert box and abs(box["y"] + box["height"] - 850) < 2 and box["width"] >= 410
    panel.get_by_role("button", name=re.compile("Close")).click()
    expect(panel).to_be_hidden()


def _first_card_box(page: Page) -> dict[str, float]:
    box = page.locator(".mg-card").first.bounding_box()
    assert box is not None
    return cast(dict[str, float], box)


def test_the_room_of_the_panel_is_reserved_so_the_cards_stay_where_they_are_on_every_page(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    """Two thirds for the entries and one third for the panel, whether or not an entry is selected: the first card keeps its place and
    width when one is selected and again when the panel is closed (it used to jump when the panel appeared)."""
    from tests.e2e.helpers import code_definition
    from tests.e2e.test_agents_page import _agent
    from tests.e2e.test_guards import _guard

    post(api, "/api/actions", name="Reserved action")
    post(api, "/api/pipelines", name="Reserved flow")
    _agent(api, "Reserved agent", user_prompt="Say hi.")
    _guard(api, "Reserved guard")
    del code_definition
    for path in ("actions", "pipelines", "agents", "guards"):
        page.goto(f"{base_url}/{path}")
        expect(page.locator(".mg-card").first).to_be_visible()
        # the page size is in the toolbar, left of the two switches, on the same line (and not under the entries)
        toolbar = page.locator(".mg__toolbar")
        size_box, view_box = (
            toolbar.locator(".mg__size").bounding_box(),
            toolbar.locator(".mg-view").bounding_box(),
        )
        assert size_box and view_box
        assert (
            size_box["x"] + size_box["width"] <= view_box["x"] + 1
            and abs(size_box["y"] - view_box["y"]) < 12
        ), path
        expect(page.locator(".mg__pager .mg__size")).to_have_count(0)
        panel = page.locator(".mg__panel")
        expect(panel).to_be_visible()  # reserved even without a selection
        expect(panel.locator(".mg-panel__placeholder")).to_be_visible()
        before = _first_card_box(page)
        shell = page.locator(".mg").bounding_box()
        panel_box = panel.bounding_box()
        assert shell and panel_box
        share = panel_box["width"] / shell["width"]
        assert 0.28 < share < 0.36, f"{path}: the panel has about a third ({share:.2f})"
        page.locator(".mg-card").first.click()
        expect(panel.locator("h2")).to_be_visible()
        after = _first_card_box(page)
        assert (after["x"], after["y"], after["width"]) == (
            before["x"],
            before["y"],
            before["width"],
        ), f"{path}: the card stays where it was when one is selected"
        panel.locator(".mg-panel__close").click()
        expect(panel.locator(".mg-panel__placeholder")).to_be_visible()
        again = _first_card_box(page)
        assert (again["x"], again["width"]) == (before["x"], before["width"]), (
            f"{path}: nor when it is closed"
        )


def test_the_page_size_is_in_the_toolbar_next_to_the_switch_and_the_pager_keeps_range_and_pages(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/actions", name="One")
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    toolbar = page.locator(".mg__toolbar")
    size = toolbar.locator(".mg__size select")
    expect(size).to_have_count(1)
    expect(page.locator(".mg__pager .mg__size")).to_have_count(0)
    expect(page.locator(".mg__pager .mg__count")).to_have_text(re.compile(r"^1.1 of 1$"))
    size_box, view_box = (
        toolbar.locator(".mg__size").bounding_box(),
        toolbar.locator(".mg-view").bounding_box(),
    )
    assert size_box and view_box
    assert size_box["x"] + size_box["width"] <= view_box["x"] + 1, "left of the switch"
    assert abs(size_box["y"] - view_box["y"]) < 12, "on the same line"
    size.select_option(label="24")  # twice the base of 12 at this window size
    # what is stored is the step (twice the base), not a number of entries: the base follows the room (ADR-069 addendum 12)
    assert page.evaluate("JSON.parse(localStorage.getItem('oa-management-actions')).step") == 2


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None
    return cast(dict[str, float], box)


def test_actions_keep_search_and_order_in_place_between_the_tabs_and_the_tabs_and_filter_have_a_row_below(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    post(api, "/api/actions", name="Plain one")
    post(api, "/api/actions", name="Guarded one", purpose="guard")
    page.goto(f"{base_url}/actions")
    expect(page.locator(".mg-card").first).to_be_visible()
    search, order = page.locator(".mg-search"), page.locator(".mg-sort")
    tabs, filt = page.locator(".mg-segment"), page.locator(".mg-filter")
    s0, o0 = _box(search), _box(order)
    # row two (tabs and filter) is below the row of search and order, not beside it
    assert _box(tabs)["y"] >= s0["y"] + s0["height"] - 1
    assert _box(filt)["y"] >= s0["y"] + s0["height"] - 1
    assert abs(_box(tabs)["y"] - _box(filt)["y"]) < 6, "tabs and filter share the second row"
    assert abs(s0["y"] - o0["y"]) < 6 and o0["x"] > s0["x"], "search, then order, on row one"
    page.get_by_role("tab", name=re.compile("Guard actions")).click()
    expect(_card(page, "Guarded one")).to_be_visible()
    s1, o1 = _box(search), _box(order)
    assert (s1["x"], s1["y"], s1["width"]) == (s0["x"], s0["y"], s0["width"]), "search stays"
    assert (o1["x"], o1["y"]) == (o0["x"], o0["y"]), "order stays"
    # the page size and the switch are on row one, right of the order
    size = _box(page.locator(".mg__size"))
    assert abs(size["y"] - s0["y"]) < 12 and size["x"] > o0["x"]


def test_pipelines_have_search_order_and_filter_in_one_row_in_that_order(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    build_pipeline(api, name="Only flow", stages=1)
    page.goto(f"{base_url}/pipelines")
    expect(page.locator(".mg-card").first).to_be_visible()
    s, o, f = (
        _box(page.locator(".mg-search")),
        _box(page.locator(".mg-sort")),
        _box(page.locator(".mg-filter")),
    )
    assert s["x"] < o["x"] < f["x"], "search, order, filter"
    assert abs(s["y"] - o["y"]) < 6 and abs(o["y"] - f["y"]) < 6, "in one row"


def test_a_card_has_no_picture_of_the_graph_and_the_graph_is_in_the_panel_tab(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    build_pipeline(api, name="Quiet flow", stages=2)
    post(api, "/api/actions", name="Quiet action")
    for path, name in (("pipelines", "Quiet flow"), ("actions", "Quiet action")):
        page.goto(f"{base_url}/{path}")
        card = _card(page, name)
        expect(card).to_be_visible()
        page.wait_for_timeout(500)  # a picture would be drawn as soon as the card is in view
        expect(card.locator(".gp__stage, .gp-node")).to_have_count(0)
        card.click()
        page.locator(".mg__panel").get_by_role("tab", name="Graph").click()
        expect(page.locator(".mg__panel .gp__stage").first).to_be_visible()


def _like_the_owners(api: httpx.Client) -> dict[str, object]:
    """Trigger, three stages of three actions each (pass, error and retry connections inside), the end."""
    pipeline = build_pipeline(api, stages=3, name="Owner flow", stage_name="Stage {}")
    for stage, first in pipeline["stages"]:
        second = node(api, pipeline, "action", stage_id=stage["id"], x=200, y=20)
        third = node(api, pipeline, "action", stage_id=stage["id"], x=400, y=120)
        connect(api, pipeline, first, "pass", second, "in")
        connect(api, pipeline, second, "pass", third, "in")
        connect(api, pipeline, third, "pass", stage, "end")
        connect(api, pipeline, first, "error", third, "in")
        connect(api, pipeline, third, "error", first, "in")
        connect(api, pipeline, second, "error", first, "in")
    return pipeline


CROSSINGS = """() => {
  const stage = document.querySelector('.mg__panel .gp__stage');
  const nodes = [...stage.querySelectorAll('.gp-node')].map((n) => ({
    id: n.dataset.nodeId, x: parseFloat(n.style.left), y: parseFloat(n.style.top), w: parseFloat(n.style.width), h: parseFloat(n.style.height) }));
  const found = [];
  for (const path of stage.querySelectorAll('.gp__link')) {
    const length = path.getTotalLength();
    for (let at = 0; at <= length; at += 3) {
      const p = path.getPointAtLength(at);
      for (const n of nodes) {
        if (n.id === path.dataset.from || n.id === path.dataset.to) continue;
        if (p.x > n.x + 1 && p.x < n.x + n.w - 1 && p.y > n.y + 1 && p.y < n.y + n.h - 1) found.push(path.dataset.edge + ' crosses ' + n.id);
      }
    }
  }
  return [...new Set(found)];
}"""


def test_the_graph_tab_draws_every_connection_and_the_stages_as_frames_around_their_actions(
    page: Page, base_url: str, api: httpx.Client
) -> None:
    pipeline = _like_the_owners(api)
    wanted = len(api.get(graph_url(pipeline)).json()["edges"])
    page.goto(f"{base_url}/pipelines")
    _card(page, "Owner flow").click()
    panel = page.locator(".mg__panel")
    panel.get_by_role("tab", name="Graph").click()
    expect(panel.locator(".gp__link")).to_have_count(wanted)  # every connection of the graph, once
    frames = panel.locator(".gp-cluster")
    expect(frames).to_have_count(3)
    for frame in frames.all():
        box = frame.bounding_box()
        assert box
        held = [n.bounding_box() for n in panel.locator(".gp-node[data-cluster]").all()]
        inside = [
            b
            for b in held
            if b
            and b["x"] >= box["x"] - 1
            and b["x"] + b["width"] <= box["x"] + box["width"] + 1
            and b["y"] >= box["y"] - 1
            and b["y"] + b["height"] <= box["y"] + box["height"] + 1
        ]
        assert len(inside) == 3, "a frame holds the three actions of its stage"
    # an error is a dashed red line, a pass is not dashed
    failing = panel.locator(".gp__link.is-failing")
    assert failing.count() == 9
    assert failing.first.evaluate("e => getComputedStyle(e).strokeDasharray") != "none"
    passing = panel.locator(".gp__link.is-passing").first
    assert passing.evaluate("e => getComputedStyle(e).strokeDasharray") == "none"
    assert page.evaluate(CROSSINGS) == [], "no line crosses a node it does not belong to"
    # the picture is one image with the names of the stages and their actions as its description
    assert "Stage 1 (" in (panel.locator(".gp").get_attribute("aria-label") or "")
    # a narrow place turns the picture; the frames and all connections stay and still no line crosses a node
    page.set_viewport_size({"width": 700, "height": 900})
    page.wait_for_timeout(300)
    expect(panel.locator(".gp__link")).to_have_count(wanted)
    expect(panel.locator(".gp-cluster")).to_have_count(3)
    assert page.evaluate(CROSSINGS) == []

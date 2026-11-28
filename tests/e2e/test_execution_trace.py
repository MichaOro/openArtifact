"""The Execution Trace: the right area of the execution page in registers (Overview, Trace, Context) and, in Trace, the rounds of an agent
step, the newest first (card #155). The model is the local stand-in; the tools are Code Tools."""

from __future__ import annotations

from typing import Any

import httpx
from playwright.sync_api import Page, expect

from tests.agent_support import FakeLlm, completion
from tests.e2e.test_agent_rounds import _limit_iterations
from tests.e2e.test_agent_tool_state import _asks, _flow, _run, _start
from tests.e2e.test_agents import agents_url, api, llm, signed_in

__all__ = ["agents_url", "api", "llm", "signed_in"]

PING = {
    "tool_name": "ping",
    "description": "Answers at once",
    "language": "python",
    "code": "print('pong')",
}
BAD = {
    "tool_name": "bad",
    "description": "Always fails",
    "language": "python",
    "code": "import sys\nprint('broken', file=sys.stderr)\nsys.exit(3)",
}


def _asks_tokens(call_id: str, name: str, tokens: int) -> dict[str, Any]:
    body = _asks((call_id, name, {}))
    body["usage"] = {"prompt_tokens": tokens - 5, "completion_tokens": 5, "total_tokens": tokens}
    return body


def _open_agent(page: Page, agents_url: str, task: dict[str, Any], run: dict[str, Any]) -> None:
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    page.locator(".ge-node--agent").first.click()


def _eight_rounds(api: httpx.Client, llm: FakeLlm) -> tuple[dict[str, Any], dict[str, Any]]:
    """An agent that calls `ping` in seven rounds and answers in the eighth."""
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    _limit_iterations(api, 12)
    llm.script = [(200, _asks_tokens(f"c{i}", "ping", 100 * i)) for i in range(1, 8)] + [
        (200, completion("All done."))
    ]
    task = _start(api, pipeline)
    return task, _run(api, task, ("done", "failed"))


def test_a_finished_agent_shows_the_newest_round_first_three_of_them_show_more_and_the_first_round_last(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    task, run = _eight_rounds(api, llm)
    assert run["status"] == "done", run
    page = signed_in
    _open_agent(page, agents_url, task, run)
    page.get_by_role("tab", name="Trace").click()
    trace = page.locator("[data-trace]")
    expect(trace).to_be_visible()
    expect(trace.locator("[data-trace-live]")).to_have_count(0)  # it has finished: no Live pill
    expect(trace.locator(".trace__facts")).to_contain_text("8 rounds")
    expect(trace.locator(".trace__facts")).to_contain_text("7 calls")
    rounds = trace.locator(".live-rounds__round")
    expect(rounds).to_have_count(4)  # the newest three and the first
    expect(rounds.nth(0)).to_contain_text("Round 8")
    expect(rounds.nth(1)).to_contain_text("Round 7")
    expect(rounds.nth(2)).to_contain_text("Round 6")
    expect(rounds.nth(3)).to_contain_text("Round 1")
    expect(rounds.nth(3)).to_contain_text("first round")
    more = trace.locator("[data-trace-more]")
    # owner decision: no counts on the button and no "hidden" text (the highest round number tells how many there are)
    expect(more).to_have_text("Show more rounds")
    expect(trace.locator(".trace__more")).not_to_contain_text("hidden")
    # the order in the page is: the three, the button, the first round (the button sits between them)
    order = trace.evaluate(
        """el => [...el.querySelectorAll('.trace__list > li')].map(
            li => li.classList.contains('trace__more') ? 'more' : li.dataset.turn)"""
    )
    assert order == ["8", "7", "6", "more", "1"], order
    more.click()
    expect(rounds).to_have_count(8)
    expect(more).to_have_count(0)
    turns = trace.evaluate(
        "el => [...el.querySelectorAll('.live-rounds__round')].map(li => Number(li.dataset.turn))"
    )
    assert turns == [8, 7, 6, 5, 4, 3, 2, 1], turns
    # a round opens to its events: the model request with its tokens, the call and what came back (no text of either)
    rounds.nth(6).locator("summary").click()
    opened = rounds.nth(6)
    expect(opened.locator(".trace__event[data-kind=model]")).to_contain_text("Model request")
    expect(opened.locator(".trace__event[data-kind=model]")).to_contain_text("200 tokens")
    expect(opened.locator(".trace__event[data-kind=tool]")).to_contain_text("ping")
    expect(opened.locator(".trace__event[data-kind=result]")).to_contain_text("Result returned")
    expect(opened).not_to_contain_text(
        "pong"
    )  # the result of the call is not in the Trace of this stage
    # the last round answered
    rounds.nth(0).locator("summary").click()
    expect(rounds.nth(0).locator(".trace__event[data-kind=answer]")).to_contain_text("Final answer")


def test_a_failed_round_is_red_and_open_and_the_search_and_the_filter_narrow_the_rounds(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING), ("code_tool", "Breaker", BAD)])
    _limit_iterations(api, 12)
    llm.script = [
        (200, _asks_tokens("c1", "ping", 100)),
        (200, _asks_tokens("c2", "bad", 200)),
        (200, _asks_tokens("c3", "ping", 300)),
        (200, completion("Done anyway.")),
    ]
    task = _start(api, pipeline)
    run = _run(api, task, ("done", "failed"))
    page = signed_in
    _open_agent(page, agents_url, task, run)
    page.get_by_role("tab", name="Trace").click()
    trace = page.locator("[data-trace]")
    failed = trace.locator(".live-rounds__round[data-turn='2']")
    expect(failed).to_have_count(1)
    expect(failed.locator("details")).to_have_attribute(
        "open", ""
    )  # a round with a failed call is open
    expect(failed.locator(".trace__event[data-kind=result][data-state=failed]")).to_be_visible()
    expect(trace.locator(".trace__facts")).to_contain_text("1 failed")
    # the filter: only the rounds with an error
    trace.locator("[data-trace-filter]").select_option("errors")
    expect(trace.locator(".live-rounds__round")).to_have_count(1)
    expect(trace.locator(".live-rounds__round")).to_contain_text("Round 2")
    trace.locator("[data-trace-filter]").select_option("all")
    # the search: the tool names
    trace.locator("[data-trace-search]").fill("bad")
    expect(trace.locator(".live-rounds__round")).to_have_count(1)
    trace.locator("[data-trace-search]").fill("nothing like this")
    expect(trace.locator(".trace__list")).to_contain_text("No round matches.")


def test_a_working_agent_has_the_live_pill_and_its_running_round_on_top_and_open(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    _limit_iterations(api, 12)
    llm.script = [
        (200, _asks_tokens("c1", "ping", 100), {}, 3.0),
        (200, _asks_tokens("c2", "ping", 200), {}, 3.0),
        (200, _asks_tokens("c3", "ping", 300), {}, 3.0),
        (200, _asks_tokens("c4", "ping", 400), {}, 3.0),
        (200, _asks_tokens("c5", "ping", 500), {}, 3.0),
        (200, completion("Finished."), {}, 12.0),
    ]
    task = _start(api, pipeline)
    run = _run(api, task, ("running", "done", "failed"))
    page = signed_in
    _open_agent(page, agents_url, task, run)
    tab = page.get_by_role("tab", name="Trace")
    expect(tab).to_be_visible(timeout=20000)
    tab.click()
    trace = page.locator("[data-trace]")
    expect(trace.locator("[data-trace-live]")).to_have_attribute("data-trace-live", "live")
    # six rounds: the newest on top is the one that waits, open, with its words
    expect(trace.locator(".live-rounds__round[data-turn='6']")).to_be_visible(timeout=40000)
    top = trace.locator(".live-rounds__round").first
    expect(top).to_contain_text("Round 6")
    expect(top.locator("details")).to_have_attribute("open", "")
    expect(top).to_contain_text("Waiting for the model's answer")
    expect(top).to_have_attribute("data-state", "running")
    # the first round stays at the bottom while rounds in between are hidden
    expect(trace.locator(".live-rounds__round").last).to_contain_text("first round")
    # it ends: the pill goes
    expect(trace.locator("[data-trace-live]")).to_have_count(0, timeout=40000)
    # a round that was open while it worked is closed again once it is done (only what the user opened or closed is kept)
    expect(
        page.locator("[data-trace] .live-rounds__round[data-turn='5'] details")
    ).not_to_have_attribute("open", "")


def test_the_registers_are_overview_trace_and_context_trace_only_for_an_agent_and_the_choice_is_kept_in_the_address(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    llm.script = [(200, _asks_tokens("c1", "ping", 100)), (200, completion("Answer."))]
    task = _start(api, pipeline)
    run = _run(api, task, ("done", "failed"))
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    tabs = page.locator("[data-panel-tabs]")
    # nothing selected: Overview and Context
    expect(tabs.get_by_role("tab")).to_have_text(["Overview", "Context"])
    expect(page.locator("[data-panel-path]")).to_be_visible()
    expect(page.locator("[data-panel-context]")).to_be_hidden()
    # an agent: the Trace register appears
    page.locator(".ge-node--agent").first.click()
    expect(tabs.get_by_role("tab")).to_have_text(["Overview", "Trace", "Context"])
    page.get_by_role("tab", name="Trace").click()
    assert page.url.endswith("#trace"), page.url
    expect(page.locator("[data-trace]")).to_be_visible()
    # another node without rounds: the Trace register is gone and Overview shows (the choice is kept for the next agent)
    page.locator(".ge-node--output").first.click()
    expect(tabs.get_by_role("tab")).to_have_text(["Overview", "Context"])
    expect(page.locator("[data-panel-path]")).to_be_visible()
    page.locator(".ge-node--agent").first.click()
    expect(
        page.locator("[data-trace]")
    ).to_be_visible()  # back on an agent: the Trace is the register again
    # the run context has its own register with the copy button
    page.get_by_role("tab", name="Context").click()
    assert page.url.endswith("#context"), page.url
    expect(page.locator("[data-panel-context]")).to_be_visible()
    expect(page.locator("[data-panel-path]")).to_be_hidden()
    # the output of the step is in the Overview (details)
    page.get_by_role("tab", name="Overview").click()
    expect(page.locator("[data-panel-detail] [data-step-output]")).to_have_count(1)
    # a reload opens the register of the address
    page.get_by_role("tab", name="Context").click()
    page.reload()
    expect(page.locator("[data-panel-context]")).to_be_visible()
    # the address opens Overview for a garbage fragment
    page.goto(
        f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1#nonsense"
    )
    expect(page.locator("[data-panel-path]")).to_be_visible()


def test_a_trigger_has_no_trace_register(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    llm.script = [(200, completion("Answer."))]
    task = _start(api, pipeline)
    run = _run(api, task, ("done", "failed"))
    page = signed_in
    page.goto(f"{agents_url}/artifacts/{task['number']}/executions/{run['execution_id']}?visit=1")
    page.locator(".ge-node--trigger").first.click()
    expect(page.locator("[data-panel-tabs]").get_by_role("tab")).to_have_text(
        ["Overview", "Context"]
    )


def test_the_trace_exists_from_the_start_and_is_empty_until_the_first_round_is_heard(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    llm.script = [(200, _asks_tokens("c1", "ping", 100), {}, 6.0), (200, completion("Answer."))]
    task = _start(api, pipeline)
    run = _run(api, task, ("running", "done", "failed"))
    page = signed_in
    _open_agent(page, agents_url, task, run)
    # the model has not answered yet: no round, no call, but the register is there
    tab = page.get_by_role("tab", name="Trace")
    expect(tab).to_be_visible(timeout=10000)
    tab.click()
    trace = page.locator("[data-trace]")
    expect(trace.locator("[data-trace-live]")).to_have_attribute("data-trace-live", "live")
    expect(trace.locator(".trace__facts")).to_contain_text("0 rounds")
    expect(trace.locator("[data-trace-empty]")).to_have_text(
        "No rounds yet. The agent has not asked the model yet."
    )
    # the round comes in and takes the place of the empty line
    expect(trace.locator(".live-rounds__round[data-turn='1']")).to_be_visible(timeout=30000)
    expect(trace.locator("[data-trace-empty]")).to_have_count(0)
    expect(trace.locator("[data-trace-live]")).to_have_count(0, timeout=40000)


def test_a_finished_agent_that_never_reached_the_model_has_a_trace_that_says_so(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    pipeline = _flow(api, llm, [("code_tool", "Pinger", PING)])
    # a prompt that reads an input nobody declares stops the node before the model is asked: no round is ever made
    for action in api.get("/api/actions").json():
        nodes = api.get(f"/api/actions/{action['id']}").json()["nodes"]
        for found in nodes:
            if found["kind"] == "agent":
                api.patch(
                    f"/api/actions/{action['id']}/nodes/{found['id']}",
                    json={"config": {"user_prompt": "Ask ${input.nobody}"}},
                ).raise_for_status()
    task = _start(api, pipeline)
    run = _run(api, task, ("done", "failed"))
    assert run["status"] == "failed", run
    page = signed_in
    _open_agent(page, agents_url, task, run)
    page.get_by_role("tab", name="Trace").click()
    trace = page.locator("[data-trace]")
    expect(trace).to_be_visible()
    expect(trace.locator("[data-trace-live]")).to_have_count(0)
    expect(trace.locator(".trace__facts")).to_contain_text("0 rounds")
    expect(trace.locator("[data-trace-empty]")).to_have_text("No rounds were recorded.")


def test_an_opened_round_is_left_aligned_with_its_time_at_the_far_right_of_the_title_line_and_no_zero_seconds(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    task, run = _eight_rounds(api, llm)
    page = signed_in
    page.set_viewport_size({"width": 1100, "height": 900})
    _open_agent(page, agents_url, task, run)
    page.get_by_role("tab", name="Trace").click()
    trace = page.locator("[data-trace]")
    rounds = trace.locator(".live-rounds__round")
    rounds.nth(1).locator("summary").click()
    opened = rounds.nth(1)
    geometry = opened.evaluate(
        """el => [...el.querySelectorAll('.trace__event')].map(ev => {
            const box = n => n && n.getBoundingClientRect();
            const line = ev.querySelector('.trace__line');
            const what = line && line.querySelector('.trace__what');
            const time = line && line.querySelector('.trace__time');
            const details = [...ev.querySelectorAll('.trace__detail')];
            return {
                kind: ev.dataset.kind, text: ev.textContent,
                block: box(ev).right, left: box(ev).left,
                titleY: what && box(what).top + box(what).height / 2, timeY: time && box(time).top + box(time).height / 2,
                timeRight: time && box(time).right, titleLeft: what && box(what).left,
                detailLefts: details.map(d => box(d).left),
            };
        })"""
    )
    kinds = [g["kind"] for g in geometry]
    assert "model" in kinds and "tool" in kinds, kinds
    for g in geometry:
        assert "0 s" not in g["text"] and "0.0 s" not in g["text"], (
            g
        )  # a duration under a tenth of a second is left out
        if g["titleLeft"] is not None:
            assert abs(g["titleLeft"] - g["left"]) <= 2, (
                g
            )  # the title starts at the left edge of the row
        for left in g["detailLefts"]:
            assert abs(left - g["left"]) <= 2, g  # the details are left-aligned with the title
    model = next(g for g in geometry if g["kind"] == "model")
    assert model["timeRight"] is not None, model  # the model request has its time
    assert abs(model["timeY"] - model["titleY"]) <= 3, model  # on the same line as its title
    assert abs(model["timeRight"] - model["block"]) <= 2, model  # at the far right of the row


def test_the_round_header_keeps_its_numbers_on_the_line_of_the_round_in_a_narrow_panel(
    signed_in: Page, agents_url: str, api: httpx.Client, llm: FakeLlm
) -> None:
    task, run = _eight_rounds(api, llm)
    page = signed_in
    page.set_viewport_size({"width": 760, "height": 900})  # the panel is about 360 px wide
    _open_agent(page, agents_url, task, run)
    page.get_by_role("tab", name="Trace").click()
    head = page.locator("[data-trace] .live-rounds__round").nth(1).locator("summary")
    expect(head).to_be_visible()
    y = head.evaluate(
        """el => ({
            head: el.getBoundingClientRect().height,
            name: el.querySelector('.trace__roundname').getBoundingClientRect().top,
            numbers: el.querySelector('.trace__numbers').getBoundingClientRect().top,
            right: el.querySelector('.trace__numbers').getBoundingClientRect().right - el.getBoundingClientRect().right,
        })"""
    )
    assert abs(y["numbers"] - y["name"]) <= 8, (
        y
    )  # the numbers sit on the line of the round name, not below it
    assert y["right"] <= 0 and y["right"] > -24, y  # at the right edge of the header

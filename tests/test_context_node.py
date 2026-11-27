"""The Build Context node (ADR-078): the package an agent is given, its sources, its size limit and what it says it left out."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.comments.schemas import CommentRead
from openartifact.engine.context import (
    NODE_OUTPUT_LIMIT_BYTES,
    NodeIndex,
    RunContext,
    RunView,
    node_key,
)
from openartifact.engine.context_builder import (
    CUT_MARK,
    CardInfo,
    PastExecution,
    cut_to,
    run_context,
    size,
)
from openartifact.engine.results import NodeResult
from openartifact.graph import context_sources as sources
from tests.helpers import build_pipeline, make_task, wait_for_run
from tests.test_execution_nodes import _definition, _start, _use

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def _comment(i: int, body: str, author: str = "ann") -> CommentRead:
    at = NOW + timedelta(minutes=i)
    return CommentRead(
        id=f"c{i}", task_id="t", body=body, author_kind="user", author=author,
        execution_id=None, created_at=at, updated_at=at,
    )  # fmt: skip


class Comments:
    def __init__(self, bodies: list[str]) -> None:
        self.all = [_comment(i, b) for i, b in enumerate(bodies, start=1)]

    async def comments(self, ref: str, newest: int | None = None) -> list[CommentRead]:
        return self.all if newest is None else self.all[-newest:]

    async def add(self, ref: str, body: str, author: Any) -> CommentRead:
        raise AssertionError("the Build Context node never writes")


class Cards:
    """The cards around the run's card, by hand."""

    def __init__(
        self,
        parent: CardInfo | None = None,
        children: list[CardInfo] | None = None,
        siblings: list[CardInfo] | None = None,
        past: list[PastExecution] | None = None,
        comments: int = 0,
    ) -> None:
        self._parent, self._children = parent, children or []
        self._siblings, self._past, self._comments = siblings or [], past or [], comments

    async def parent(self, task_id: str) -> CardInfo | None:
        return self._parent

    async def children(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        return self._children[:limit], len(self._children)

    async def siblings(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        return self._siblings[:limit], len(self._siblings)

    async def comment_count(self, task_id: str) -> int:
        return self._comments

    async def executions(
        self, task_id: str, exclude: str | None, newest: int
    ) -> tuple[list[PastExecution], int]:
        return self._past[-newest:], len(self._past)


def _view(**card: Any) -> RunView:
    base = {"title": "Fix the login", "body": "Users cannot log in.", "number": 12, "id": "task-1"}
    context = RunContext({"card": {**base, **card}})
    return RunView(context, NodeIndex(), "task-1", "exec-now")


def _data(result: NodeResult) -> dict[str, Any]:
    assert result.data is not None
    return result.data


async def _build(
    config: dict[str, Any],
    view: RunView | None = None,
    comments: Comments | None = None,
    cards: Cards | None = None,
) -> NodeResult:
    return await run_context(
        config, view=view or _view(), cards=cards or Cards(), comments=comments or Comments([])
    )


# ── the sources as data ──────────────────────────────────────────────


def test_a_stored_list_gets_every_option_of_its_sources_and_keeps_the_order() -> None:
    stored = sources.normalise([{"source": "comments"}, {"source": "parent"}, {"source": "card"}])
    assert stored == [
        {"source": "comments", "count": 20},
        {"source": "parent", "detail": "title"},
        {"source": "card"},
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("card", "must be a list"),
        ([{"source": "weather"}], "Unknown source 'weather'"),
        ([{"source": "card"}, {"source": "card"}], "there twice"),
        ([{"source": "comments", "count": 0}], "number of items is 1 to 100"),
        ([{"source": "comments", "count": True}], "number of items is 1 to 100"),
        ([{"source": "executions", "count": 11}], "number of items is 1 to 10"),
        ([{"source": "parent", "detail": "everything"}], "detail is one of title, text"),
        ([{"source": "card", "count": 3}], "no option 'count'"),
        ([{"source": "nodes", "names": ["A", "A"]}], "named twice"),
        ([{"source": "nodes", "names": [f"n{i}" for i in range(11)]}], "at most 10 nodes"),
        ([{"source": s} for s in ("card", "fields", "comments", "parent", "children", "siblings", "nodes", "handovers", "executions")] + [{"source": "x"}], "At most 9 sources"),
    ],
)  # fmt: skip
def test_a_list_that_does_not_fit_is_refused_in_plain_words(value: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        sources.normalise(value)


def test_the_bounds_and_defaults_of_the_settings_are_those_the_engine_uses() -> None:
    from openartifact.engine import context_builder as builder
    from openartifact.graph.node_types import node_type
    from openartifact.models import NodeKind

    settings = {s.key: s for s in node_type(NodeKind.CONTEXT).settings}
    size_limit, item_limit = settings["size_limit"], settings["item_limit"]
    assert (size_limit.minimum, size_limit.maximum, size_limit.default) == (
        builder.LIMIT_MIN, builder.LIMIT_MAX, builder.LIMIT_DEFAULT,
    )  # fmt: skip
    assert (item_limit.minimum, item_limit.maximum, item_limit.default) == (
        builder.ITEM_MIN, builder.ITEM_MAX, builder.ITEM_DEFAULT,
    )  # fmt: skip
    assert settings["sources"].default == sources.DEFAULT_SOURCES


def test_cut_to_never_splits_a_character_and_always_ends_with_the_mark() -> None:
    text, cut = cut_to("ä" * 100, 51)
    assert cut and text.endswith(CUT_MARK) and size(text) <= 51
    text.encode("utf-8").decode("utf-8")  # a whole character at the end
    assert cut_to("short", 51) == ("short", False)


# ── the card, its fields, its comments ───────────────────────────────


async def test_the_package_has_a_heading_per_source_in_the_order_the_user_gave() -> None:
    result = await _build(
        {"sources": [{"source": "comments", "count": 5}, {"source": "card"}]},
        comments=Comments(["first comment", "second comment"]),
        cards=Cards(comments=2),
    )
    assert result.outcome == "pass"
    headings = [line for line in result.output.splitlines() if line.startswith("## ")]
    assert headings == ["## Comments", "## Title and body"]
    assert "#12 Fix the login\n\nUsers cannot log in." in result.output
    assert [p["source"] for p in _data(result)["included"]] == ["comments", "card"]


async def test_the_fields_of_the_card_are_listed_and_an_empty_one_is_left_out() -> None:
    view = _view(priority="high", owner="", estimate=3, done=False)
    result = await _build({"sources": [{"source": "fields"}]}, view=view)
    assert "## Fields\n\npriority: high\nestimate: 3\ndone: false" in result.output
    assert "owner" not in result.output


async def test_the_newest_comments_that_fit_are_kept_whole_oldest_first_and_the_rest_is_counted() -> (
    None
):
    bodies = [f"comment {i} " + "x" * 200 for i in range(1, 31)]
    result = await _build(
        {"sources": [{"source": "comments", "count": 30}], "size_limit": 1024},
        comments=Comments(bodies),
        cards=Cards(comments=30),
    )
    out = result.output
    assert size(out) <= 1024
    (part,) = _data(result)["included"]
    kept = part["items"]
    assert 2 <= kept < 30 and part["available"] == 30
    assert f"[... {30 - kept} older comments left out]" in out
    assert f"## Comments ({kept} of 30, oldest first)" in out
    newest = list(range(31 - kept, 31))
    assert f"comment {newest[0] - 1} " not in out  # the next older one was left out ...
    assert 1024 - size(out) < 250  # ... because it did not fit (a comment block is about 245 bytes)
    assert all(
        out.index(f"comment {a} ") < out.index(f"comment {b} ")
        for a, b in itertools.pairwise(newest)
    )
    for number in newest:  # whole comments: each one ends with its own last character
        assert f"comment {number} " + "x" * 200 in out


async def test_the_count_of_the_user_holds_back_older_comments_but_the_package_still_says_so() -> (
    None
):
    result = await _build(
        {"sources": [{"source": "comments", "count": 2}]},
        comments=Comments(["a", "b", "c", "d"]),
        cards=Cards(comments=4),
    )
    assert "[... 2 older comments left out]" in result.output
    assert "] ann (user):\nc" in result.output and "] ann (user):\na" not in result.output


async def test_a_long_comment_is_cut_at_the_item_limit_with_the_mark_and_the_data_counts_it() -> (
    None
):
    result = await _build(
        {"sources": [{"source": "comments", "count": 5}], "item_limit": 256},
        comments=Comments(["short", "z" * 5000]),
        cards=Cards(comments=2),
    )
    assert CUT_MARK in result.output
    (part,) = _data(result)["included"]
    assert part["cut"] == 1 and part["items"] == 2


async def test_the_package_never_exceeds_the_limit_whatever_the_text_and_the_limit() -> None:
    bodies = ["ä" * 700, "日本語" * 300, "plain " * 400, "x" * 3000]
    for limit in (1024, 1500, 2047, 4096, 8192, 32768):
        for count in (1, 3):
            result = await _build(
                {
                    "sources": [
                        {"source": "fields"},
                        {"source": "comments", "count": 100},
                        {"source": "card"},
                        {"source": "executions", "count": 3},
                    ],
                    "size_limit": limit,
                },
                view=_view(body="B" * 5000, note="n" * 900),
                comments=Comments(bodies * count),
                cards=Cards(
                    comments=4 * count,
                    past=[PastExecution(i, "done", None, "user", "P", NOW, "n", "o" * 600) for i in range(1, 6)],
                ),
            )  # fmt: skip
            assert size(result.output) <= limit, (limit, count, size(result.output))
            assert _data(result)["size_bytes"] == size(result.output)
            assert _data(result)["limit_bytes"] == limit


async def test_the_card_is_reserved_first_and_cut_last_the_others_give_way() -> None:
    long_body = "word " * 1000  # 5000 bytes
    result = await _build(
        {"sources": [{"source": "comments", "count": 5}, {"source": "card"}], "size_limit": 1024},
        view=_view(body=long_body),
        comments=Comments(["a comment"]),
        cards=Cards(comments=1),
    )
    assert size(result.output) <= 1024
    assert result.output.startswith("## Title and body\n\n#12 Fix the login")
    assert result.output.endswith(CUT_MARK)  # the card's text is what was cut
    assert [o["source"] for o in _data(result)["omitted"]] == ["comments"]
    assert "did not fit" in _data(result)["omitted"][0]["reason"]
    (card,) = _data(result)["included"]
    assert card["source"] == "card" and card["cut"] == 1


async def test_a_card_that_fits_keeps_its_place_in_the_order_and_is_not_cut() -> None:
    result = await _build(
        {"sources": [{"source": "comments", "count": 5}, {"source": "card"}]},
        comments=Comments(["only comment"]),
        cards=Cards(comments=1),
    )
    assert result.output.index("## Comments") < result.output.index("## Title and body")
    assert CUT_MARK not in result.output
    assert _data(result)["omitted"] == []


# ── the text of cards is data, never a reference ─────────────────────


async def test_references_and_secret_names_in_cards_and_comments_stay_literal() -> None:
    view = RunView(
        RunContext(
            {
                "vars": {"token": "SECRETVALUE"},
                "card": {"title": "${secret:TOKEN}", "body": "${var.token} ${node.X.output}", "number": 1},
            }
        ),
        NodeIndex(), "task-1", "exec-now",
    )  # fmt: skip
    result = await _build(
        {"sources": [{"source": "card"}, {"source": "comments", "count": 3}]},
        view=view,
        comments=Comments(["use ${secret:TOKEN} and ${card.title}"]),
        cards=Cards(comments=1),
    )
    assert result.outcome == "pass"
    for text in (
        "${secret:TOKEN}",
        "${var.token} ${node.X.output}",
        "use ${secret:TOKEN} and ${card.title}",
    ):
        assert text in result.output
    assert "SECRETVALUE" not in result.output


# ── related cards, earlier results, earlier executions ───────────────


def _card(number: int, title: str, body: str = "", lane: str | None = "Backlog") -> CardInfo:
    return CardInfo(number, title, body, lane)


async def test_parent_children_and_siblings_show_titles_or_title_and_text() -> None:
    cards = Cards(
        parent=_card(1, "Epic", "The big picture", "MVP"),
        children=[_card(20, "Child one", "child text"), _card(21, "Child two")],
        siblings=[_card(30, "Sibling", "sibling text")],
    )
    result = await _build(
        {
            "sources": [
                {"source": "parent", "detail": "text"},
                {"source": "children"},
                {"source": "siblings", "detail": "text"},
            ]
        },
        cards=cards,
    )
    out = result.output
    assert "## Parent card\n\n#1 Epic (MVP)\n\nThe big picture" in out
    assert (
        "## Child cards\n\n#20 Child one (Backlog)\n#21 Child two (Backlog)" in out
    )  # titles only: one per line
    assert "child text" not in out
    assert "## Sibling cards\n\n#30 Sibling (Backlog)\n\nsibling text" in out


async def test_children_that_do_not_fit_are_counted_and_the_last_ones_go_first() -> None:
    children = [_card(100 + i, f"child {i:03d} " + "t" * 100) for i in range(40)]
    result = await _build(
        {"sources": [{"source": "children", "count": 40}], "size_limit": 1024},
        cards=Cards(children=children),
    )
    assert size(result.output) <= 1024
    assert "child 000" in result.output and "child 039" not in result.output
    assert "more child cards left out]" in result.output
    (part,) = _data(result)["included"]
    assert part["available"] == 40 and part["items"] < 40


async def test_a_source_with_nothing_to_give_is_listed_with_its_reason() -> None:
    result = await _build(
        {"sources": [{"source": "card"}, {"source": "parent"}, {"source": "children"}, {"source": "comments", "count": 5}]},
    )  # fmt: skip
    omitted = {o["source"]: o["reason"] for o in _data(result)["omitted"]}
    assert omitted == {
        "parent": "the card has no parent",
        "children": "the card has no child cards",
        "comments": "the card has no comments",
    }
    assert [p["source"] for p in _data(result)["included"]] == ["card"]


async def test_results_of_named_nodes_are_used_and_a_node_that_has_not_run_is_said_not_to_have() -> (
    None
):
    context = RunContext(
        {
            "card": {"title": "T", "number": 1},
            "nodes": {
                "Classify": {
                    "name": "Classify",
                    "kind": "agent",
                    "outcome": "pass",
                    "output": "bug",
                },
                "Fetch": {
                    "name": "Fetch",
                    "kind": "http",
                    "outcome": "fail",
                    "output": "",
                    "truncated": True,
                },
            },
        }
    )
    view = RunView(context, NodeIndex(), "task-1", "exec-now")
    result = await _build(
        {"sources": [{"source": "nodes", "names": ["Classify", "Fetch", "Later"]}]}, view=view
    )
    assert "### Classify (agent, pass)\nbug" in result.output
    assert "### Fetch (http, fail)\n(no output) [output was cut by the run]" in result.output
    assert _data(result)["omitted"] == [
        {"source": "nodes", "reason": 'the node "Later" has not run in this execution'}
    ]


async def test_earlier_executions_say_how_they_ended_and_what_their_last_step_gave() -> None:
    past = [
        PastExecution(1, "failed", '"Action" has no On Pass connection', "user", "Build", NOW),
        PastExecution(2, "done", None, "api", "Build", NOW, "Summarize", "all good\nlong text"),
    ]
    result = await _build(
        {"sources": [{"source": "executions", "count": 2}]}, cards=Cards(past=past)
    )
    out = result.output
    assert out.index("#1 failed") < out.index("#2 done")  # oldest first
    assert 'Note: "Action" has no On Pass connection' in out
    assert "Last result (Summarize):\nall good\nlong text" in out
    assert "started by api" in out


# ── the node as a node ───────────────────────────────────────────────


async def test_no_source_is_a_failure_that_says_so_and_a_missing_list_builds_the_default() -> None:
    nothing = await _build({"sources": []})
    assert (nothing.outcome, nothing.reason) == (
        "fail",
        "No source is chosen: add at least one source to build a package from",
    )
    default = await _build({}, comments=Comments(["hi"]), cards=Cards(comments=1))
    assert default.outcome == "pass"
    assert [p["source"] for p in _data(default)["included"]] == ["card", "comments"]


async def test_a_run_without_a_card_gives_an_empty_package_and_says_why() -> None:
    result = await run_context(
        {"sources": [{"source": "card"}, {"source": "comments", "count": 3}]},
        view=RunView(), cards=Cards(), comments=Comments([]),
    )  # fmt: skip
    assert result.outcome == "pass" and result.output == ""
    assert result.reason is not None and result.reason.startswith("Nothing was included")
    assert {o["source"] for o in _data(result)["omitted"]} == {"card", "comments"}


async def test_an_invalid_list_fails_the_node_with_the_reason() -> None:
    result = await _build({"sources": [{"source": "weather"}]})
    assert result.outcome == "fail" and "Unknown source 'weather'" in str(result.reason)


async def test_the_result_asks_the_run_context_to_keep_the_whole_package() -> None:
    result = await _build(
        {"sources": [{"source": "card"}], "size_limit": 16384},
        view=_view(body="b" * 9000),
    )
    assert size(result.output) > NODE_OUTPUT_LIMIT_BYTES and result.keep_bytes == 16384
    context = RunContext()
    context.record({"name": "Build", "kind": "context"}, result, "pass")
    assert context.nodes["Build"]["output"] == result.output  # not cut at the 4 KiB of other nodes
    other = RunContext()
    other.record({"name": "Plain", "kind": "code"}, NodeResult("pass", output="q" * 9000), "pass")
    assert other.nodes["Plain"]["truncated"] is True


async def test_the_approximate_tokens_follow_the_size() -> None:
    result = await _build({"sources": [{"source": "card"}]})
    assert _data(result)["approx_tokens"] == -(-_data(result)["size_bytes"] // 4)


# ── in a real run ────────────────────────────────────────────────────


def _step(client: TestClient, task: dict[str, Any]) -> dict[str, Any]:
    run = wait_for_run(client, task, "done")
    (step,) = [r for r in run["node_results"] if r["kind"] == "context"]
    result: dict[str, Any] = step
    return result


def test_a_run_builds_the_package_from_the_real_card_and_its_comments(client: TestClient) -> None:
    task = make_task(client, "Fix the login")
    parent = make_task(client, "Epic")
    client.patch(f"/api/tasks/{task['id']}", json={"parent_id": parent["id"]})
    for body in ("first", "second ${secret:TOKEN}"):
        client.post(f"/api/tasks/{task['id']}/comments", json={"body": body})
    pipeline = build_pipeline(client, stages=1)
    _use(
        client,
        pipeline,
        _definition(
            client, "context",
            sources=[{"source": "card"}, {"source": "parent"}, {"source": "comments", "count": 5}],
        ),
    )  # fmt: skip
    _start(client, pipeline, task)
    step = _step(client, task)
    assert step["outcome"] == "pass"
    out = step["output"]
    assert "## Title and body" in out and "Fix the login" in out
    assert f"## Parent card\n\n#{parent['number']} Epic" in out
    assert "second ${secret:TOKEN}" in out  # literal
    assert [p["source"] for p in step["data"]["included"]] == ["card", "parent", "comments"]
    assert step["data"]["limit_bytes"] == 8192


def test_a_package_larger_than_a_nodes_usual_output_stays_whole_in_the_run_context(
    client: TestClient,
) -> None:
    task = make_task(client, "Big")
    client.patch(f"/api/tasks/{task['id']}", json={"body": "b" * 6000})
    pipeline = build_pipeline(client, stages=1)
    _use(client, pipeline, _definition(client, "context", sources=[{"source": "card"}]))
    _start(client, pipeline, task)
    step = _step(client, task)
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    detail = client.get(f"/api/tasks/{task['id']}/executions/{execution['id']}").json()
    entry = detail["context"]["nodes"][node_key(step["node_name"])]
    assert size(entry["output"]) > NODE_OUTPUT_LIMIT_BYTES  # a node's usual 4 KiB would have cut it
    assert entry["truncated"] is False and entry["output"].endswith("b" * 100)
    assert entry["data"]["size_bytes"] == size(entry["output"])

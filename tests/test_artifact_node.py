"""The Artifact node (ADR-055): reads and writes the comments of the run's own artifact, within the limits of the context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from openartifact.comments.schemas import Author, CommentRead
from openartifact.engine.artifact_runner import ADD, GET, run_artifact, transcript
from openartifact.engine.context import NODE_OUTPUT_LIMIT_BYTES, NodeIndex, RunContext, RunView
from tests.helpers import build_pipeline, make_task, wait_for_run
from tests.test_execution_nodes import _definition, _start, _use


def _comment(i: int, body: str, author: str = "ann", kind: str = "user") -> CommentRead:
    at = datetime(2026, 11, 23, 9, i, tzinfo=UTC)
    return CommentRead(
        id=f"c{i}", task_id="t", body=body, author_kind=kind, author=author,
        execution_id=None, created_at=at, updated_at=at,
    )  # fmt: skip


def _step(client: TestClient, task: dict[str, Any], status: str = "done") -> dict[str, Any]:
    run = wait_for_run(client, task, status)
    (step,) = [r for r in run["node_results"] if r["kind"] == "artifact"]
    result: dict[str, Any] = step
    return result


def _flow(client: TestClient, task: dict[str, Any], **config: Any) -> dict[str, Any]:
    pipeline = build_pipeline(client, stages=1)
    _use(client, pipeline, _definition(client, "artifact", **config))
    _start(client, pipeline, task)
    return _step(client, task, "failed" if config.get("expect_fail") else "done")


# ── the transcript ───────────────────────────────────────────────────


def test_the_newest_comments_that_fit_are_kept_and_the_older_ones_counted() -> None:
    comments = [_comment(i, f"comment number {i} " + "x" * 80) for i in range(1, 9)]
    text, data, left_out = transcript(comments, max_chars=200, max_total=300)
    assert [d["body"][:16] for d in data] == ["comment number 7", "comment number 8"]
    assert left_out == 6 and len(text) <= 300
    assert text.index("number 7") < text.index("number 8")  # oldest of the kept ones first


def test_a_long_comment_is_cut_with_a_mark_and_the_newest_is_always_kept() -> None:
    text, data, left_out = transcript([_comment(1, "a" * 5000)], max_chars=50, max_total=100)
    assert data[0]["body"].endswith("…[cut]") and len(data[0]["body"]) == 50
    assert left_out == 0 and len(text) <= 100


def test_a_transcript_of_many_multibyte_comments_stays_under_the_output_limit() -> None:
    comments = [_comment(i % 59, "ä" * 400) for i in range(1, 30)]
    text, _, _ = transcript(comments, max_chars=400, max_total=4000)
    assert len(text.encode()) < NODE_OUTPUT_LIMIT_BYTES


class _Gateway:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, Author]] = []

    async def comments(self, ref: str, newest: int | None = None) -> list[CommentRead]:
        return []

    async def add(self, ref: str, body: str, author: Author) -> CommentRead:
        self.added.append((ref, body, author))
        return _comment(1, body)


async def test_the_text_of_add_comment_may_hold_references_and_is_written_to_the_runs_artifact() -> (
    None
):
    view = RunView(RunContext({"vars": {"who": "Ann"}}), NodeIndex(), "task-1", "exec-1")
    gateway = _Gateway()
    result = await run_artifact(
        {"operation": ADD, "text": "Hello ${var.who}\n  indented"},
        node_name="Notify", view=view, gateway=gateway, author_factory=Author,
    )  # fmt: skip
    assert result.outcome == "pass" and result.data == {"id": "c1"}
    assert gateway.added == [("task-1", "Hello Ann\n  indented", Author("run", "Notify", "exec-1"))]


async def test_an_empty_text_a_missing_artifact_or_a_missing_service_fails_with_a_reason() -> None:
    view = RunView(RunContext({"vars": {"empty": ""}}), NodeIndex(), "task-1", "exec-1")
    empty = await run_artifact(
        {"operation": ADD, "text": "${var.empty}"},
        node_name="N", view=view, gateway=_Gateway(), author_factory=Author,
    )  # fmt: skip
    assert (empty.outcome, empty.reason) == ("fail", "The comment is empty")
    no_card = await run_artifact(
        {"operation": GET}, node_name="N", view=RunView(), gateway=_Gateway(), author_factory=Author
    )
    assert no_card.outcome == "fail" and "not available" in str(no_card.reason)
    bad_ref = await run_artifact(
        {"operation": ADD, "text": "${var.nothing}"},
        node_name="N", view=view, gateway=_Gateway(), author_factory=Author,
    )  # fmt: skip
    assert bad_ref.outcome == "fail" and "nothing" in str(bad_ref.reason)


# ── in a real run ────────────────────────────────────────────────────


def test_add_comment_writes_a_run_comment_with_the_node_name_and_the_execution(
    client: TestClient,
) -> None:
    task, other = make_task(client), make_task(client, "Other")
    step = _flow(client, task, operation="Add comment", text="Checked.\nAll fine.")
    assert step["outcome"] == "pass" and step["data"]["id"]
    (comment,) = client.get(f"/api/tasks/{task['id']}/comments").json()
    assert comment["id"] == step["data"]["id"]
    assert (comment["author_kind"], comment["body"]) == ("run", "Checked.\nAll fine.")
    assert comment["author"] == step["node_name"]
    execution = client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    assert comment["execution_id"] == execution["id"]
    assert client.get(f"/api/tasks/{other['id']}/comments").json() == []  # only its own artifact


def test_get_comments_gives_a_transcript_and_a_list_within_the_limits(client: TestClient) -> None:
    task = make_task(client)
    url = f"/api/tasks/{task['id']}/comments"
    for body in ("first", "second " + "w" * 300, "third"):
        client.post(url, json={"body": body})
    step = _flow(client, task, operation="Get comments", limit=2, max_chars=40, max_total=1000)
    assert [c["body"][:6] for c in step["data"]["comments"]] == ["second", "third"]
    assert step["data"]["comments"][0]["body"].endswith("…[cut]")
    assert set(step["data"]["comments"][0]) == {"author", "kind", "body", "at"}
    assert step["data"]["comments"][1]["author"] == "You"
    assert "first" not in step["output"] and "third" in step["output"]
    assert len(step["output"].encode()) < NODE_OUTPUT_LIMIT_BYTES


def test_get_comments_of_an_artifact_without_comments_says_so(client: TestClient) -> None:
    step = _flow(client, make_task(client), operation="Get comments")
    assert step["output"] == "No comments yet" and step["data"]["comments"] == []


def test_a_secret_reference_in_the_text_is_refused_when_the_node_is_saved(
    client: TestClient,
) -> None:
    action = _definition(client, "artifact", operation="Add comment", text="x")
    node = action["node"]
    refused = client.patch(
        f"/api/actions/{action['id']}/nodes/{node['id']}",
        json={"config": {"operation": "Add comment", "text": "key ${secret:TOKEN}"}},
    )
    assert refused.status_code == 422
    assert "secret" in refused.text.lower()


def test_the_node_is_described_for_the_editor_without_a_target_artifact_setting(
    client: TestClient,
) -> None:
    described = {t["kind"]: t for t in client.get("/api/node-types").json()}["artifact"]
    assert described["label"] == "Artifact"
    keys = [s["key"] for s in described["settings"]]
    assert keys[:2] == ["operation", "limit"] and not {"artifact", "task", "task_id"} & set(keys)


def test_a_later_node_reads_the_output_and_the_data_of_an_artifact_node_in_a_real_run(
    client: TestClient,
) -> None:
    """``${(Artifact).output}`` and ``${(Artifact).data.count}`` resolve for the node of a kind the editor did not list before."""
    from tests.helpers import connect as _connect
    from tests.helpers import graph_url as _url
    from tests.helpers import node as _node

    task = make_task(client)
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "first"})
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "second"})
    pipeline = build_pipeline(client, stages=1)
    definition = _definition(client, "artifact")
    reader = definition["node"]
    graph = client.get(_url(definition)).json()
    edge = next(
        e for e in graph["edges"] if e["source_id"] == reader["id"] and e["source_port"] == "pass"
    )
    client.delete(f"{_url(definition)}/edges/{edge['id']}")
    check = _node(
        client,
        definition,
        "if",
        name="Count",
        config={
            "left_1": f"${{({reader['name']}).data.count}}",
            "operator_1": "equals",
            "right_1": "2",
            "left_2": f"${{({reader['name']}).output}}",
            "operator_2": "contains",
            "right_2": "second",
        },
    )
    _connect(client, definition, reader, "pass", check, "in")
    _connect(client, definition, check, "yes", definition["output"], "pass")
    _use(client, pipeline, definition)
    _start(client, pipeline, task)
    run = wait_for_run(client, task, "done")
    step = next(r for r in run["node_results"] if r["kind"] == "if")
    assert step["port"] == "yes", (
        step
    )  # both references were read: two comments, one of them "second"

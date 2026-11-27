"""The run context: storage, writing, references, masking, API exposure and the migration (ADR-033).

The first half needs no engine (the context and the resolver are plain objects); the second half runs
real actions: a chain of Code and HTTP nodes where a later node uses what an earlier one set.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import openartifact.database as db_mod
from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine.context import (
    CONTEXT_LIMIT_BYTES,
    NODE_OUTPUT_LIMIT_BYTES,
    VARS_LIMIT_BYTES,
    ContextError,
    NodeIndex,
    RunContext,
    RunView,
    check_url_placement,
    check_vars,
    node_key,
    problems,
)
from openartifact.engine.results import NodeResult
from tests.helpers import (
    alembic_config,
    build_pipeline,
    connect,
    graph_url,
    link,
    make_task,
    node,
    post,
    run_of,
    wait_for_run,
    wait_until,
)

TOKEN = "ctx-api-token-" + "x" * 20
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


# ── helpers ──────────────────────────────────────────────────────────


def _result(**fields: Any) -> NodeResult:
    return NodeResult(**{"outcome": "pass", **fields})


def _definition_of(*nodes: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    """The graph dict (as the snapshot has it) of an action with these ``(kind, name, config)`` nodes."""
    return {
        "name": "Load",
        "nodes": [
            {"id": f"n{i}", "kind": kind, "name": name, "config": config}
            for i, (kind, name, config) in enumerate(nodes)
        ],
    }


def _view(context: RunContext | None = None, *nodes: tuple[str, str, dict[str, Any]]) -> RunView:
    return RunView(context or RunContext(), NodeIndex.of_graphs([_definition_of(*nodes)]))


def _ran(name: str, **fields: Any) -> RunContext:
    context = RunContext()
    context.record({"name": name, "kind": "code"}, _result(**fields), "pass")
    return context


# ── unit: names, variables, recording ────────────────────────────────


def test_a_node_key_is_its_name_with_other_characters_as_underscores() -> None:
    assert node_key("Fetch user") == "Fetch_user"
    assert node_key("  a-b_c.d/é ") == "a-b_c_d__"
    assert node_key("Code") == "Code"


def test_valid_variables_pass_and_invalid_ones_say_why() -> None:
    ok = {"a": 1, "b_2": "x", "c": [1, {"d": None}], "e": {"f": {"g": 1.5}}, "t": True}
    assert check_vars(ok) == ok
    for raw, text in [
        ({"Bad": 1}, "variable name 'Bad'"),
        ({"1a": 1}, "variable name '1a'"),
        ({"a" * 65: 1}, "variable name"),
        ({"a": {"b": {"c": {"d": {"e": 1}}}}}, "variable 'a': lists and objects may be nested"),
        ({"a": float("inf")}, "must be finite"),
        ({"a": {1: 2}}, "keys must be text"),
        ("text", "must be an object"),
        ({f"v{i}": 1 for i in range(101)}, "at most 100"),
    ]:
        with pytest.raises(ContextError, match=text):
            check_vars(raw)


def test_variables_are_capped_and_a_write_that_does_not_fit_changes_nothing() -> None:
    context = RunContext()
    context.set_vars({"keep": "k"})
    with pytest.raises(ContextError, match="exceed the limit"):
        context.set_vars({"big": "x" * VARS_LIMIT_BYTES})
    assert context.vars == {"keep": "k"}


def test_a_node_output_is_cut_in_the_context_and_marked() -> None:
    context = _ran("A", output="é" * NODE_OUTPUT_LIMIT_BYTES)
    entry = context.nodes["A"]
    assert entry["truncated"] is True and entry["output"].endswith("[output truncated]")
    assert len(entry["output"].encode()) <= NODE_OUTPUT_LIMIT_BYTES + 20
    assert "truncated" not in _ran("B", output="short").nodes["B"]


def test_the_latest_result_of_a_node_wins_and_the_oldest_lose_their_output_first() -> None:
    context = RunContext()
    context.record({"name": "A", "kind": "code"}, _result(output="first"), "pass")
    context.record({"name": "A", "kind": "code"}, _result(output="second"), "pass")
    assert context.nodes["A"]["output"] == "second"
    for i in range(30):  # 30 x ~4 KiB is more than the limit
        context.record({"name": f"N{i}", "kind": "code"}, _result(output="y" * 4000), "pass")
    assert len(context.dumps().encode()) <= CONTEXT_LIMIT_BYTES
    assert context.nodes["A"]["output"] == "[output removed: the context is limited]"
    assert context.nodes["N29"]["output"] == "y" * 4000  # the newest keeps its output
    assert list(context.nodes)[-1] == "N29"


def test_variables_are_never_dropped_to_make_room() -> None:
    context = RunContext()
    context.set_vars({"v": "x" * (VARS_LIMIT_BYTES - 100)})
    for i in range(40):
        context.record(
            {"name": f"N{i}", "kind": "http"},
            _result(output="y" * 4000, data={"k": "z" * 500}),
            "pass",
        )
    assert len(context.vars["v"]) == VARS_LIMIT_BYTES - 100
    assert len(context.dumps().encode()) <= CONTEXT_LIMIT_BYTES


def test_a_stored_text_that_is_not_a_context_reads_as_empty() -> None:
    for text in (None, "", "{", "[]", '{"vars": 1, "nodes": []}'):
        context = RunContext.loads(text)
        assert (context.vars, context.nodes) == ({}, {})


# ── unit: the resolver ───────────────────────────────────────────────


def test_every_field_of_a_node_can_be_referenced() -> None:
    context = _ran(
        "Fetch user",
        output="body text",
        exit_code=0,
        reason="why",
        data={"status": 200, "user": {"tags": ["a", "b"], "id": 7}, "ok": True},
    )
    view = _view(context, ("http", "Fetch user", {}))
    expect = {
        "output": "body text",
        "exit_code": "0",
        "outcome": "pass",
        "reason": "why",
        "data.status": "200",
        "data.user.id": "7",
        "data.user.tags.1": "b",
        "data.user": '{"tags":["a","b"],"id":7}',
        "data.ok": "true",
    }
    for field, text in expect.items():
        assert view.render("${node.Fetch_user." + field + "}") == text
    assert view.render("a ${node.Fetch_user.output}, ${node.Fetch_user.outcome}!") == (
        "a body text, pass!"
    )


def test_a_node_can_be_referenced_by_its_name_in_parentheses() -> None:
    context = _ran("Code: hello", output="hi", data={"step": 1, "a": {"b": [5, 6]}})
    view = _view(context, ("code", "Code: hello", {}))
    assert view.render("${(Code: hello).output}|${(Code: hello).data.step}") == "hi|1"
    assert (
        view.render("${( Code: hello ).data.a.b.1}") == "6"
    )  # blanks around the name do not matter
    assert view.render("${node.Code__hello.output}") == "hi"  # the older spelling stays valid
    with pytest.raises(ContextError, match=r"no node is named"):
        view.render("${(Nope).output}")
    with pytest.raises(ContextError, match="malformed reference"):
        view.render("${(Code: hello).bogus}")
    with pytest.raises(ContextError, match="malformed reference"):
        view.render("${(Code: hello}")
    assert problems("${(Missing node).output}", view.index, lambda _k: False) == [
        '${(Missing node).output}: no node is named "Missing_node"'
    ]


def test_null_fields_render_as_json_null_and_variables_as_text_or_json() -> None:
    context = _ran("A", output="")
    context.set_vars({"s": "text", "n": 3, "l": [1, "x"], "z": None})
    view = _view(context, ("code", "A", {}))
    assert view.render("${node.A.exit_code}|${node.A.reason}|${node.A.data}") == "null|null|null"
    assert view.render("${var.s} ${var.n} ${var.l} ${var.z}") == 'text 3 [1,"x"] null'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("${node.Nope.output}", 'no node is named "Nope"'),
        ("${node.A.data.missing}", "the data of node \"A\" has no 'missing'"),
        ("${node.A.data.x.y}", "has no 'y'"),
        ("${node.B.output}", 'node "B" has not run yet'),
        ("${var.unset}", "variable 'unset' is not set"),
        ("${node.A.bogus}", "malformed reference"),
        ("${node.A.output.more}", "malformed reference"),
        ("${var.Upper}", "malformed reference"),
        ("${node.}", "malformed reference"),
        ("${var.}", "malformed reference"),
    ],
)
def test_an_unresolvable_reference_fails_and_names_itself(text: str, message: str) -> None:
    context = _ran("A", data={"x": 1})
    view = _view(context, ("code", "A", {}), ("code", "B", {}))
    with pytest.raises(ContextError, match=message) as error:
        view.render(f"before {text} after")
    assert text in str(error.value)


def test_a_data_reference_on_a_node_without_data_says_so() -> None:
    view = _view(_ran("A"), ("code", "A", {}))
    with pytest.raises(ContextError, match='node "A" has no data'):
        view.render("${node.A.data.id}")


def test_two_nodes_with_one_name_make_the_reference_ambiguous_even_if_one_ran() -> None:
    view = RunView(
        _ran("Same", output="x"),
        NodeIndex.of_graphs(
            [
                {"name": "Load", "nodes": [{"id": "1", "kind": "code", "name": "Same"}]},
                {"name": "Store", "nodes": [{"id": "2", "kind": "http", "name": "Same"}]},
            ]
        ),
    )
    with pytest.raises(ContextError) as error:
        view.render("${node.Same.output}")
    text = str(error.value)
    assert 'ambiguous node name "Same"' in text
    assert '"Same" (code) in action "Load"' in text and '"Same" (http) in action "Store"' in text


def test_the_same_node_in_two_pipelines_is_not_ambiguous() -> None:
    graph = {"name": "Load", "nodes": [{"id": "1", "kind": "code", "name": "A"}]}
    assert NodeIndex.of_graphs([graph, graph]).lookup("A").node_id == "1"


def test_replaced_values_are_never_scanned_again() -> None:
    context = _ran("A", output="${var.x} and ${secret:TOKEN} and ${node.A.output}")
    context.set_vars({"x": "${secret:TOKEN}"})
    view = _view(context, ("code", "A", {}))
    secrets = {"TOKEN": "hunter2"}
    out = view.render("${node.A.output} | ${var.x} | ${secret:TOKEN}", secrets=secrets)
    assert out == "${var.x} and ${secret:TOKEN} and ${node.A.output} | ${secret:TOKEN} | hunter2"


def test_secret_references_are_left_alone_unless_a_value_is_given() -> None:
    view = _view()
    assert view.render("a ${secret:X} b") == "a ${secret:X} b"
    assert view.render("a ${secret:X} b", secrets={"X": "v"}) == "a v b"


def test_replaced_text_is_percent_encoded_in_a_url_and_only_there() -> None:
    context = _ran("A", output="a b/c?d=é")
    context.set_vars({"q": "x&y"})
    view = _view(context, ("code", "A", {}))
    assert view.render("/p/${node.A.output}?q=${var.q}", percent_encode=True) == (
        "/p/a%20b%2Fc%3Fd%3D%C3%A9?q=x%26y"
    )
    assert view.render("${var.q}") == "x&y"


def test_a_reference_is_not_allowed_in_the_scheme_or_the_host() -> None:
    for url in (
        "${var.u}://x/y",
        "http://${var.h}/p",
        "http://h:${var.p}/p",
        "http://u@${var.h}/",
        "${var.u}",
    ):
        with pytest.raises(ContextError, match="not in the scheme or the host"):
            check_url_placement(url)
    check_url_placement("http://h/p/${var.a}?x=${node.A.output}#${var.f}")
    check_url_placement("http://h/p")


def test_save_time_hints_name_ambiguous_unknown_and_malformed_references() -> None:
    local = NodeIndex.of_graphs(
        [_definition_of(("code", "Dup", {}), ("code", "Dup", {}), ("code", "Fine", {}))]
    )
    text = "${node.Dup.output} ${node.Fine.output} ${node.Far.output} ${node.Gone.output} ${node.x} ${var.ok}"
    hints = problems(text, local, lambda key: key == "Far")
    assert len(hints) == 3
    assert 'ambiguous node name "Dup"' in hints[0]
    assert hints[1] == '${node.Gone.output}: no node is named "Gone"'
    assert "malformed reference ${node.x}" in hints[2]


# ── engine: the chain of nodes ───────────────────────────────────────

Make = Callable[..., TestClient]


@pytest.fixture
def make_client(migrated_settings: Settings) -> Generator[Make, None, None]:
    stack: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        settings = migrated_settings.model_copy(
            update={"http_allow_private_networks": True, **overrides}
        )
        client = TestClient(_create_app(settings))
        client.__enter__()
        stack.append(client)
        return client

    yield make
    for client in stack:
        client.__exit__(None, None, None)


@pytest.fixture
def ctx_client(make_client: Make) -> TestClient:
    return make_client()


def _chain(
    client: TestClient, *nodes: tuple[str, str, dict[str, Any]], name: str = "Chain"
) -> dict[str, Any]:
    """An action definition trigger -> nodes in a row (On Pass) -> Output; On Fail goes to the Output's fail."""
    action = post(client, "/api/actions", name=name)
    graph = client.get(graph_url(action)).json()["nodes"]
    trigger = next(n for n in graph if n["kind"] == "trigger")
    output = next(n for n in graph if n["kind"] == "output")
    client.patch(f"{graph_url(action)}/nodes/{output['id']}", json={"fail_enabled": True})
    previous, port = trigger, "out"
    made = []
    for kind, label, config in nodes:
        item = node(client, action, kind, name=label, config=config)
        connect(client, action, previous, port, item, "in")
        connect(client, action, item, "fail", output, "fail")
        previous, port = item, "pass"
        made.append(item)
    connect(client, action, previous, port, output, "pass")
    action["nodes_made"] = made
    return action


def _use_chain(client: TestClient, *nodes: tuple[str, str, dict[str, Any]]) -> tuple[Any, Any, Any]:
    pipeline = build_pipeline(client, stages=1)
    action = _chain(client, *nodes)
    link(client, pipeline, pipeline["stages"][0][1], action)
    return pipeline, make_task(client), action


def _start(client: TestClient, pipeline: dict[str, Any], task: dict[str, Any]) -> None:
    post(client, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])


def _execution_id(client: TestClient, task: dict[str, Any]) -> str:
    return str(run_of(client, task)["execution_id"])


def _detail(client: TestClient, task: dict[str, Any], execution_id: str | None = None) -> Any:
    execution_id = execution_id or _execution_id(client, task)
    response = client.get(f"/api/tasks/{task['id']}/executions/{execution_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _code(source: str, language: str = "sh", **config: Any) -> dict[str, Any]:
    return {"language": language, "code": source, **config}


SETTER = _code(
    """echo log line
echo '{"ok": true, "vars": {"user": "bob", "n": 7}, "data": {"id": 7, "tags": ["a"]}}'"""
)


def test_the_context_has_every_executed_node_and_the_variables_a_code_node_set(
    ctx_client: TestClient,
) -> None:
    pipeline, task, _ = _use_chain(
        ctx_client, ("code", "Set it", SETTER), ("code", "Then", _code("printf second"))
    )
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    context = _detail(ctx_client, task)["context"]
    assert context["vars"] == {"user": "bob", "n": 7}
    assert list(context["nodes"]) == ["Set_it", "Then"]
    first = context["nodes"]["Set_it"]
    assert (first["name"], first["kind"], first["outcome"], first["port"]) == (
        "Set it",
        "code",
        "pass",
        "pass",
    )
    assert first["exit_code"] == 0 and first["output"].startswith("log line\n")
    assert first["data"] == {"id": 7, "tags": ["a"]} and first["at"].endswith("Z")
    assert context["nodes"]["Then"]["output"] == "second"
    # the run read carries only the size; the list of executions nothing of it
    assert run_of(ctx_client, task)["context_size"] > 10
    listed = ctx_client.get(f"/api/tasks/{task['id']}/executions").json()["items"][0]
    assert "context" not in listed and "'vars'" not in str(ctx_client.get("/api/runs").json())
    assert (
        ctx_client.get(f"/api/tasks/{task['id']}/executions/{listed['id']}/context").json()
        == context
    )


def test_the_context_after_every_node_survives_a_restart_of_the_server(
    migrated_settings: Settings,
) -> None:
    settings = migrated_settings.model_copy(update={"code_nodes_without_token": True})
    with TestClient(_create_app(settings)) as client:
        pipeline, task, _ = _use_chain(
            client, ("code", "Set it", SETTER), ("code", "Slow", _code("sleep 30"))
        )
        _start(client, pipeline, task)
        before = wait_until(
            lambda: _detail(client, task)["context"], lambda c: "Set_it" in c["nodes"]
        )
        assert "Slow" not in before["nodes"]  # a crash loses at most the node that was running
        execution_id = _execution_id(client, task)
    with TestClient(_create_app(settings)) as client:  # recover() stops the interrupted run
        detail = _detail(client, task, execution_id)
        assert (detail["status"], detail["note"]) == ("stopped", "Interrupted by restart")
        assert detail["context"] == before
        assert run_of(client, task)["context_size"] > 10


def test_every_start_begins_with_an_empty_context_and_the_old_one_stays_in_its_execution(
    ctx_client: TestClient,
) -> None:
    pipeline, task, action = _use_chain(ctx_client, ("code", "Set it", SETTER))
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    first_id = _execution_id(ctx_client, task)
    ctx_client.patch(
        f"{graph_url(action)}/nodes/{action['nodes_made'][0]['id']}",
        json={"config": {"code": 'echo \'{"ok": true, "vars": {"other": 1}}\''}},
    )
    _start(ctx_client, pipeline, task)
    run = wait_until(lambda: run_of(ctx_client, task), lambda r: r["execution_id"] != first_id)
    wait_for_run(ctx_client, task, "done", where=lambda r: r["execution_id"] == run["execution_id"])
    assert _detail(ctx_client, task)["context"]["vars"] == {"other": 1}
    assert _detail(ctx_client, task, first_id)["context"]["vars"] == {"user": "bob", "n": 7}


def test_a_node_that_ran_again_keeps_its_latest_result(ctx_client: TestClient) -> None:
    pipeline = build_pipeline(ctx_client, stages=2)
    action = _chain(ctx_client, ("code", "Stamp", _code("date +%s%N")))
    for _stage, shell in pipeline["stages"]:
        link(ctx_client, pipeline, shell, action)
    task = make_task(ctx_client)
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    detail = _detail(ctx_client, task)
    stamps = [s["output"] for s in detail["steps"] if s["kind"] == "code"]
    assert len(stamps) == 2 and stamps[0] != stamps[1]
    assert detail["context"]["nodes"]["Stamp"]["output"] == stamps[1]


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (
            'echo \'{"ok": true, "vars": {"Bad Name": 1}}\'',
            "Invalid vars: variable name 'Bad Name'",
        ),
        ('echo \'{"ok": true, "vars": "text"}\'', "Invalid vars: 'vars' must be an object"),
        (
            'echo \'{"ok": true, "vars": {"a": {"b": {"c": {"d": {"e": 1}}}}}}\'',
            "Invalid vars: variable 'a': lists and objects may be nested",
        ),
        (
            'echo \'{"ok": true, "vars": {"a": NaN}}\'',
            "Invalid vars: variable 'a': a number must be finite",
        ),
    ],
)
def test_invalid_variables_fail_the_node_with_the_reason_and_set_nothing(
    ctx_client: TestClient, source: str, reason: str
) -> None:
    pipeline, task, _ = _use_chain(
        ctx_client,
        ("code", "Setter", _code('echo \'{"ok": true, "vars": {"fine": 1}}\'')),
        ("code", "Bad", _code(source)),
    )
    _start(ctx_client, pipeline, task)
    run = wait_for_run(ctx_client, task, "failed")
    step = next(r for r in run["node_results"] if r["node_name"] == "Bad")
    assert step["outcome"] == "fail" and step["reason"].startswith(reason)
    context = _detail(ctx_client, task)["context"]
    assert context["vars"] == {"fine": 1}
    assert context["nodes"]["Bad"]["outcome"] == "fail"


def test_variables_that_do_not_fit_fail_the_writing_node(ctx_client: TestClient) -> None:
    big = _code(
        "import json,sys\n"
        "print(json.dumps({'ok': True, 'vars': {sys.argv[0][-1:] + 'v': 'x' * 7000}}))",
        "python",
    )
    # each node sets a 7000 character variable under a different name: the fifth does not fit in 32 KiB
    nodes = [
        ("code", f"Big {i}", {**big, "code": big["code"].replace("sys.argv[0][-1:]", f"'a{i}'")})
        for i in range(6)
    ]
    pipeline, task, _ = _use_chain(ctx_client, *nodes)
    _start(ctx_client, pipeline, task)
    run = wait_for_run(ctx_client, task, "failed")
    failed = [r for r in run["node_results"] if r["outcome"] == "fail" and r["kind"] == "code"]
    assert [r["node_name"] for r in failed] == ["Big 4"]
    assert "exceed the limit of 32 KiB" in failed[0]["reason"]
    assert sorted(_detail(ctx_client, task)["context"]["vars"]) == ["a0v", "a1v", "a2v", "a3v"]


def test_a_long_output_is_cut_in_the_context_and_whole_in_the_step(ctx_client: TestClient) -> None:
    pipeline, task, _ = _use_chain(
        ctx_client, ("code", "Long", _code("head -c 10000 /dev/zero | tr '\\0' x"))
    )
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    detail = _detail(ctx_client, task)
    entry = detail["context"]["nodes"]["Long"]
    assert entry["truncated"] is True and entry["output"].endswith("[output truncated]")
    assert len(entry["output"]) < 4200
    assert next(s for s in detail["steps"] if s["kind"] == "code")["output"] == "x" * 10000


def test_a_code_node_reads_the_context_as_a_read_only_file(ctx_client: TestClient) -> None:
    reader = _code(
        "import json, os\n"
        "c = json.load(open('context.json'))\n"
        "print(c['vars']['user'], c['nodes']['Setter']['outcome'], oct(os.stat('context.json').st_mode & 0o777))",
        "python",
    )
    pipeline, task, _ = _use_chain(
        ctx_client, ("code", "Setter", SETTER), ("code", "Reader", reader)
    )
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    assert _detail(ctx_client, task)["context"]["nodes"]["Reader"]["output"] == "bob pass 0o400\n"


def test_the_text_of_a_code_node_is_never_interpolated(ctx_client: TestClient) -> None:
    pipeline, task, _ = _use_chain(
        ctx_client,
        ("code", "Setter", SETTER),
        ("code", "Echo", _code("echo '${var.user} ${node.Setter.output}'")),
    )
    _start(ctx_client, pipeline, task)
    wait_for_run(ctx_client, task, "done")
    assert _detail(ctx_client, task)["context"]["nodes"]["Echo"]["output"] == (
        "${var.user} ${node.Setter.output}\n"
    )


# ── engine: HTTP nodes use the context ───────────────────────────────


@contextmanager
def _recording_server() -> Iterator[tuple[int, list[dict[str, Any]]]]:
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
            seen.append({"path": self.path, "x_user": self.headers.get("X-User"), "body": body})
            reply = b'{"echo": "${var.user}", "n": 5}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        yield httpd.server_address[1], seen
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_node_two_steps_later_uses_a_value_an_earlier_node_set(ctx_client: TestClient) -> None:
    with _recording_server() as (port, seen):
        call = {
            "method": "POST",
            "url": f"http://127.0.0.1:{port}/u/${{var.user}}/${{node.Middle.output}}?id=${{node.Set_it.data.id}}",
            "headers": "X-User: ${var.user}",
            "body": '{"seen": "${node.Middle.output}", "tag": "${node.Set_it.data.tags.0}"}',
        }
        pipeline, task, _ = _use_chain(
            ctx_client,
            ("code", "Set it", SETTER),
            ("code", "Middle", _code("printf 'm m'")),
            ("http", "Caller", call),
            (
                "http",
                "Second",
                {
                    **call,
                    "url": f"http://127.0.0.1:{port}/again/${{node.Caller.data.status}}",
                    "body": "${node.Caller.output}",
                },
            ),
        )
        _start(ctx_client, pipeline, task)
        wait_for_run(ctx_client, task, "done")
    assert seen[0] == {
        "path": "/u/bob/m%20m?id=7",
        "x_user": "bob",
        "body": '{"seen": "m m", "tag": "a"}',
    }
    # the response of the server contained a reference: it is text, never replaced
    assert seen[1] == {
        "path": "/again/200",
        "x_user": "bob",
        "body": '{"echo": "${var.user}", "n": 5}',
    }
    nodes = _detail(ctx_client, task)["context"]["nodes"]
    assert nodes["Caller"]["data"]["status"] == 200 and nodes["Caller"]["kind"] == "http"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            {"url": "http://127.0.0.1:1/${node.Ghost.output}"},
            '${node.Ghost.output}: no node is named "Ghost"',
        ),
        ({"url": "http://127.0.0.1:1/${var.nope}"}, "${var.nope}: variable 'nope' is not set"),
        (
            {"url": "http://127.0.0.1:1/", "body": "${node.Later.output}"},
            '${node.Later.output}: node "Later" has not run yet',
        ),
        (
            {"url": "http://127.0.0.1:1/", "headers": "X: ${node.Caller.bogus}"},
            "malformed reference",
        ),
    ],
)
def test_an_unresolvable_reference_fails_the_http_node_with_a_visible_reason(
    ctx_client: TestClient, config: dict[str, Any], message: str
) -> None:
    pipeline = build_pipeline(ctx_client, stages=1)
    action = _chain(ctx_client, ("http", "Caller", config), ("code", "Later", _code("echo later")))
    link(ctx_client, pipeline, pipeline["stages"][0][1], action)
    task = make_task(ctx_client)
    _start(ctx_client, pipeline, task)
    run = wait_for_run(ctx_client, task, "failed")
    step = next(r for r in run["node_results"] if r["kind"] == "http")
    assert step["outcome"] == "fail" and message in step["reason"]


def test_an_ambiguous_name_fails_the_node_that_uses_it(ctx_client: TestClient) -> None:
    pipeline, task, _ = _use_chain(
        ctx_client,
        ("code", "Twin", _code("echo a")),
        ("code", "Twin", _code("echo b")),
        ("http", "Caller", {"url": "http://127.0.0.1:1/${node.Twin.output}"}),
    )
    _start(ctx_client, pipeline, task)
    run = wait_for_run(ctx_client, task, "failed")
    reason = next(r for r in run["node_results"] if r["kind"] == "http")["reason"]
    assert 'ambiguous node name "Twin"' in reason and reason.count('"Twin" (code)') == 2


def test_references_before_the_path_are_refused_when_saving_and_never_run(
    ctx_client: TestClient,
) -> None:
    action = _chain(ctx_client)
    item = node(ctx_client, action, "http")
    response = ctx_client.patch(
        f"{graph_url(action)}/nodes/{item['id']}", json={"config": {"url": "http://${var.h}/x"}}
    )
    assert response.status_code == 422 and "not in the scheme or the host" in response.text


def test_saving_a_node_reports_hints_about_its_references_without_blocking(
    ctx_client: TestClient,
) -> None:
    action = _chain(ctx_client, ("code", "Dup", _code("echo")), ("code", "Dup", _code("echo")))
    item = node(ctx_client, action, "http")
    body = {
        "config": {
            "url": "http://h/${node.Dup.output}/${node.Ghost.output}",
            "body": "${node.Dup.data.x} ${var.fine} ${node.bad}",
        }
    }
    response = ctx_client.patch(f"{graph_url(action)}/nodes/{item['id']}", json=body)
    assert response.status_code == 200
    hints = response.json()["warnings"]
    assert sum('ambiguous node name "Dup"' in h for h in hints) == 2
    assert any('no node is named "Ghost"' in h for h in hints)
    assert any("malformed reference ${node.bad}" in h for h in hints)
    clean = ctx_client.patch(
        f"{graph_url(action)}/nodes/{item['id']}", json={"config": {"url": "http://h/", "body": ""}}
    )
    assert clean.json()["warnings"] == []
    assert ctx_client.get(graph_url(action)).json()["nodes"][0]["warnings"] == []


# ── masking ──────────────────────────────────────────────────────────


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": "k" * 40, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def test_a_secret_a_code_node_printed_is_masked_in_the_context_and_in_the_file_of_the_next_node(
    secured: TestClient,
) -> None:
    assert secured.put("/api/secrets/TOKEN", json={"value": "s3cr3t-value"}).status_code == 201
    # the script itself prints the value as a variable and as data
    printer = _code(
        'echo "$TOKEN"\n'
        'printf \'{"ok": true, "vars": {"leak": "%s"}, "data": {"t": "%s"}}\\n\' "$TOKEN" "$TOKEN"',
        secrets="TOKEN",
    )
    reader = _code("cat context.json")
    pipeline, task, _ = _use_chain(
        secured, ("code", "Printer", printer), ("code", "Reader", reader)
    )
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    detail = _detail(secured, task)
    assert "s3cr3t-value" not in json.dumps(detail)
    assert detail["context"]["vars"] == {"leak": "***"}
    assert detail["context"]["nodes"]["Printer"]["data"] == {"t": "***"}
    assert detail["context"]["nodes"]["Printer"]["output"].startswith("***\n")
    seen_by_reader = detail["context"]["nodes"]["Reader"]["output"]
    assert "***" in seen_by_reader and "s3cr3t-value" not in seen_by_reader
    assert json.loads(seen_by_reader)["vars"] == {"leak": "***"}


def test_a_secret_used_in_a_request_is_not_in_the_context(secured: TestClient) -> None:
    secured.put("/api/secrets/TOKEN", json={"value": "tok-9988"})

    class Echo(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            reply = self.headers.get("Authorization", "").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        call = {
            "url": f"http://127.0.0.1:{httpd.server_address[1]}/",
            "headers": "Authorization: Bearer ${secret:TOKEN}",
        }
        pipeline, task, _ = _use_chain(secured, ("http", "Call", call))
        _start(secured, pipeline, task)
        wait_for_run(secured, task, "done")
    finally:
        httpd.shutdown()
        httpd.server_close()
    detail = _detail(secured, task)
    assert detail["context"]["nodes"]["Call"]["output"] == "Bearer ***"
    assert "tok-9988" not in json.dumps(detail)


# ── API exposure ─────────────────────────────────────────────────────


def test_the_context_is_in_the_detail_of_every_interface_and_not_in_the_lists(
    secured: TestClient,
) -> None:
    pipeline, task, _ = _use_chain(secured, ("code", "Set it", SETTER))
    _start(secured, pipeline, task)
    wait_for_run(secured, task, "done")
    execution_id = _execution_id(secured, task)
    expected = _detail(secured, task)["context"]
    assert expected["vars"]["user"] == "bob"
    ref = task["number"]
    v1 = secured.get(f"/api/v1/artifacts/{ref}/executions/{execution_id}").json()
    assert v1["context"] == expected
    assert (
        secured.get(f"/api/v1/artifacts/{ref}/executions/{execution_id}/context").json() == expected
    )
    mcp_headers = {**HEADERS, "Accept": "application/json, text/event-stream"}
    called = secured.post(
        "/mcp",
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_execution",
                "arguments": {"artifact": str(ref), "execution": execution_id},
            },
        },
    )
    assert called.status_code == 200 and "context" in called.text and "Set_it" in called.text
    for url in (
        f"/api/tasks/{task['id']}/executions",
        f"/api/v1/artifacts/{ref}/executions",
        "/api/executions",
        "/api/v1/executions",
        "/api/runs",
        f"/api/tasks/{task['id']}/executions/{execution_id}/flow",
    ):
        assert '"context"' not in secured.get(url).text and "Set_it" not in secured.get(url).text, (
            url
        )
    assert secured.get(f"/api/v1/artifacts/{ref}/executions/nope/context").status_code == 404


# ── storage: one copy, gone with the execution, one statement per node ──


def _context_rows(path: Any) -> list[tuple[str, str]]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute("SELECT id, context FROM executions"))


def _db_has(path: Any, text: str) -> bool:
    """Whether a column of any table but ``executions.context`` holds the text."""
    with sqlite3.connect(path) as conn:
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall():
            for column in [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]:
                if (table, column) == ("executions", "context"):
                    continue
                query = f'SELECT 1 FROM "{table}" WHERE CAST("{column}" AS TEXT) LIKE ? LIMIT 1'
                if conn.execute(query, (f"%{text}%",)).fetchone():
                    return True
    return False


def _two_executions(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    pipeline, task, _ = _use_chain(client, ("code", "Set it", SETTER))
    ids: list[str] = []
    for _ in range(2):
        _start(client, pipeline, task)
        seen = tuple(ids)

        def new(run: dict[str, Any], seen: tuple[str, ...] = seen) -> bool:
            return bool(run["execution_id"] not in seen)

        wait_for_run(client, task, "done", where=new)
        ids.append(_execution_id(client, task))
    return pipeline, task, ids


def test_no_table_but_the_execution_keeps_the_context(
    ctx_client: TestClient, migrated_settings: Settings
) -> None:
    _two_executions(ctx_client)
    path = migrated_settings.data_dir / migrated_settings.database_filename
    rows = _context_rows(path)
    assert len(rows) == 2 and all('"user":"bob"' in context for _, context in rows)
    assert not _db_has(
        path, '"user":"bob"'
    )  # the steps and the run hold the output, not the context
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(pipeline_runs)")}
    assert "context" not in columns


@pytest.mark.parametrize("how", ["one", "clear", "rule", "artifact"])
def test_the_context_goes_with_its_execution(
    ctx_client: TestClient, migrated_settings: Settings, how: str
) -> None:
    _, task, ids = _two_executions(ctx_client)
    base = f"/api/tasks/{task['id']}"
    path = migrated_settings.data_dir / migrated_settings.database_filename
    if how == "one":
        assert ctx_client.delete(f"{base}/executions/{ids[0]}").status_code == 204
        assert [i for i, _ in _context_rows(path)] == [ids[1]]
        return
    if how == "clear":
        ctx_client.delete(f"{base}/executions")
        left = {i for i, _ in _context_rows(path)}
        assert left <= set()  # finished executions are all deleted, so are their contexts
    elif how == "rule":
        beyond = {"type": "condition", "field": "position", "op": "beyond", "value": 1}
        rules = [{"when": {"type": "group", "mode": "all", "items": [beyond]}, "action": "delete"}]
        ctx_client.put("/api/settings/retention", json={"rules": rules})
        assert [i for i, _ in _context_rows(path)] == [
            ids[1]
        ]  # a retention rule removes the older one
    else:
        assert ctx_client.delete(base).status_code == 204
        assert _context_rows(path) == []
    assert not _db_has(path, '"user":"bob"')


def test_writing_the_context_adds_no_statement_to_a_node(ctx_client: TestClient) -> None:
    """One UPDATE of the execution row per recorded step carries the step count and the context."""
    pipeline, task, _ = _use_chain(
        ctx_client,
        ("code", "A", _code("echo a")),
        ("code", "B", _code("echo b")),
        ("code", "C", _code("echo c")),
    )
    statements: list[str] = []
    engine = db_mod._engine
    assert engine is not None

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        _start(ctx_client, pipeline, task)
        wait_for_run(ctx_client, task, "done")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    writes = [s for s in statements if s.startswith("UPDATE executions") and "context" in s]
    assert len(writes) == 3 and all("step_count" in s for s in writes)  # the step's own update
    reads = [s for s in statements if "executions.context" in s and "length(" not in s]
    assert len(reads) == 1  # the context is read once, when the run starts


# ── migration 0028 ───────────────────────────────────────────────────


def test_migration_0028_adds_the_column_and_goes_down_and_up_with_data(
    unmigrated_settings: Settings, at_revision: Callable[[str], Any]
) -> None:
    path = at_revision("0027")
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO lane_titles (status, title) VALUES ('backlog', 'Ideas')")
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at) "
            "VALUES ('t', 'T', 'backlog', 1, 0, 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO executions (id, task_id, number, status, started_by, created_at, started_at) "
            "VALUES ('e', 't', 1, 'done', 'user', '2026-01-01', '2026-01-01')"
        )
    cfg = alembic_config()

    def state() -> tuple[set[str], Any, Any]:
        with sqlite3.connect(path) as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(executions)")}
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            lanes = (
                conn.execute("SELECT status, title FROM lane_titles").fetchall()
                if "lane_titles" in tables
                else None
            )
            ctx = (
                conn.execute("SELECT context FROM executions").fetchone()
                if "context" in columns
                else None
            )
            return columns, lanes, ctx

    assert "context" not in state()[0]
    command.upgrade(cfg, "0028")
    columns, lanes, ctx = state()
    assert "context" in columns and ctx == ("{}",) and lanes == [("backlog", "Ideas")]
    with sqlite3.connect(path) as conn:
        assert "context" not in {r[1] for r in conn.execute("PRAGMA table_info(pipeline_runs)")}
        conn.execute('UPDATE executions SET context = \'{"vars":{"a":1}}\'')
    command.downgrade(cfg, "0027")
    columns, lanes, _ = state()
    assert "context" not in columns and lanes == [("backlog", "Ideas")]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone() == (1,)
    command.upgrade(cfg, "head")
    assert state()[2] == ("{}",)


@pytest.mark.parametrize(
    "kind", ["github", "postgres", "artifact", "set", "agent", "http", "if", "switch", "timer"]
)
def test_the_result_of_any_kind_of_node_can_be_referenced(kind: str) -> None:
    """A reference does not depend on the kind: what a node left in the context is read by its name (the editor offers it
    for every kind whose manifest says it leaves a result)."""
    context = RunContext()
    context.record(
        {"name": "Left", "kind": kind},
        _result(output="done", data={"rows": [{"a": 1}], "count": 1}),
        "pass",
    )
    view = _view(context, (kind, "Left", {}))
    assert (
        view.render("${(Left).output}|${(Left).data.count}|${(Left).data.rows.0.a}") == "done|1|1"
    )

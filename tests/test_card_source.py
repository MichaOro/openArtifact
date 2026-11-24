"""The card as a source of the run (ADR-064): the built-in references, the reserved field names, and the input
mapping of an agent node end to end against the fake model (what the model RECEIVED is asserted, not the stored
mapping)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import context
from tests.agent_support import HEADERS as AGENT_HEADERS
from tests.agent_support import SECURE, FakeLlm, fake_llm, make_agent, make_provider
from tests.helpers import alembic_config
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import connect as _connect
from tests.helpers import graph_url as _url
from tests.helpers import node as _node
from tests.helpers import post as _post
from tests.helpers import wait_for_run as _wait


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(AGENT_HEADERS)
        yield client


@pytest.fixture
def llm(api: TestClient) -> Iterator[FakeLlm]:
    with fake_llm() as server:
        make_provider(api, server)
        yield server


EPIC = "Epic A"
BODY = 'Line one\nLine "two" with ${not.a.reference} and a lone $ and {{braces}}'


def _task(api: TestClient, title: str = EPIC, body: str = BODY, **fields: Any) -> dict[str, Any]:
    response = api.post("/api/tasks", json={"title": title, "body": body, "fields": fields})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _define_fields(api: TestClient, *names: str) -> None:
    fields = [{"name": n, "label": n.title(), "kind": "text"} for n in names]
    response = api.put("/api/artifact-fields", json={"fields": fields})
    assert response.status_code == 200, response.text


def _flow(
    api: TestClient,
    agent: dict[str, Any],
    inputs: str,
    before: list[tuple[str, str, dict[str, Any]]] = (),  # type: ignore[assignment]
    after_agent: bool = True,
) -> dict[str, Any]:
    """A pipeline whose action is: trigger -> [before nodes] -> Agent node "Ask" -> Output, one stage."""
    action = _post(api, "/api/actions", name="Answer")
    graph = api.get(_url(action)).json()
    trigger = next(n for n in graph["nodes"] if n["kind"] == "trigger")
    output = next(n for n in graph["nodes"] if n["kind"] == "output")
    for edge in graph["edges"]:
        api.delete(f"{_url(action)}/edges/{edge['id']}")
    source, port = trigger, "out"
    for kind, name, config in before:
        made = _node(api, action, kind, name=name, config=config)
        _connect(api, action, source, port, made, "in")
        source, port = made, "pass"
    ask = _node(
        api, action, "agent", name="Ask", config={"agent_id": agent["id"], "inputs": inputs}
    )
    _connect(api, action, source, port, ask, "in")
    _connect(api, action, ask, "pass", output, "pass")
    pipeline = _pipeline(api, stages=1)
    shell = pipeline["stages"][0][1]
    api.patch(f"{_url(pipeline)}/nodes/{shell['id']}", json={"definition_id": action["id"]})
    return pipeline


def _run(
    api: TestClient, pipeline: dict[str, Any], task: dict[str, Any], status: str = "done"
) -> dict[str, Any]:
    _post(api, f"/api/tasks/{task['id']}/run", pipeline_id=pipeline["id"])
    run = _wait(api, task, status, timeout=30)
    run["task"] = task
    return run


def _asked(llm: FakeLlm, index: int = -1) -> str:
    """The user message of a request the fake model received."""
    return str(llm.completions()[index]["json"]["messages"][-1]["content"])


def _step(api: TestClient, run: dict[str, Any], name: str = "Ask") -> dict[str, Any]:
    step = next(r for r in run["node_results"] if r["node_name"] == name)
    url = f"/api/tasks/{run['task']['id']}/executions/{run['execution_id']}/steps/{step['id']}"
    return api.get(url).json()  # type: ignore[no-any-return]


# ── the card a run starts with ───────────────────────────────────────


def test_the_card_of_a_run_holds_the_built_ins_and_the_custom_fields(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_fields(api, "test")
    task = _task(api, test="custom value")
    agent = make_agent(api, user_prompt="x ${input.t}", inputs=[{"name": "t", "default": "-"}])
    run = _run(api, _flow(api, agent, "t = ${card.title}"), task)
    detail = api.get(f"/api/tasks/{task['id']}/executions/{run['execution_id']}").json()
    card = detail["context"]["card"]
    assert card["id"] == task["id"] and card["number"] == task["number"]
    assert card["title"] == EPIC and card["body"] == BODY
    assert "text" not in card  # derived when `${card.text}` is read: the body is not held twice
    assert card["test"] == "custom value"


def test_text_is_the_number_and_the_title_alone_when_the_body_is_empty(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api, title="Only a title", body="")
    agent = make_agent(api, user_prompt="x ${input.t}", inputs=[{"name": "t", "default": "-"}])
    run = _run(api, _flow(api, agent, "t = ${card.text}"), task)
    assert _asked(llm) == f"x #{task['number']} Only a title"
    assert run["status"] == "done"


@pytest.mark.parametrize("name", ["title", "body", "number", "id", "text"])
def test_a_field_cannot_take_a_name_the_card_already_has(api: TestClient, name: str) -> None:
    response = api.put(
        "/api/artifact-fields", json={"fields": [{"name": name, "label": "X", "kind": "text"}]}
    )
    assert response.status_code == 422
    assert f"Field {name}" in response.text and "built into every artifact" in response.text


# ── (a) an explicit mapping of a string input ────────────────────────


def test_a_string_input_mapped_to_the_title_the_body_and_a_custom_field_reaches_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_fields(api, "test")
    task = _task(api, test="custom value")
    agent = make_agent(
        api,
        user_prompt="T=${input.t}|B=${input.b}|F=${input.f}",
        inputs=[
            {"name": "t", "required": True},
            {"name": "b", "required": True},
            {"name": "f", "required": True},
        ],
    )
    _run(api, _flow(api, agent, "t = ${card.title}\nb = ${card.body}\nf = ${card.test}"), task)
    assert _asked(llm) == f"T={EPIC}|B={BODY}|F=custom value"


# ── (b) the artifact input ───────────────────────────────────────────


def test_an_artifact_input_pre_filled_with_the_card_text_shows_number_title_and_body_to_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(
        api,
        user_prompt="Epic:\n${input.epic}",
        inputs=[{"name": "epic", "type": "artifact", "required": True}],
    )
    run = _run(api, _flow(api, agent, "epic = ${card.text}"), task)
    asked = _asked(llm)
    assert asked == f"Epic:\n#{task['number']} {EPIC}\n\n{BODY}"
    detail = _step(api, run)["detail"]
    assert [(i["name"], i["type"], i["state"]) for i in detail["inputs"]] == [
        ("epic", "artifact", "mapped")
    ]


def test_the_artifact_type_is_a_type_of_the_agent_api(api: TestClient) -> None:
    agent = make_agent(
        api,
        user_prompt="${input.epic}",
        inputs=[{"name": "epic", "type": "artifact"}],
        publish=False,
    )
    assert api.get(f"/api/agents/{agent['id']}").json()["draft"]["inputs"][0]["type"] == "artifact"
    bad = api.put(
        f"/api/agents/{agent['id']}/draft",
        json={"user_prompt": "x", "inputs": [{"name": "epic", "type": "artifact", "default": "x"}]},
    )
    assert bad.status_code == 422  # an artifact input is the card: it has no default text


# ── (c) other sources in the mapping ─────────────────────────────────


def test_an_input_mapped_to_the_comments_of_the_artifact_node_reaches_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    for text in ("first answer", "second answer"):
        api.post(f"/api/tasks/{task['id']}/comments", json={"body": text})
    agent = make_agent(
        api, user_prompt="Notes:\n${input.notes}", inputs=[{"name": "notes", "required": True}]
    )
    pipeline = _flow(
        api,
        agent,
        "notes = ${(Notes).output}",
        before=[("artifact", "Notes", {"operation": "Get comments"})],
    )
    _run(api, pipeline, task)
    asked = _asked(llm)
    assert "first answer" in asked and "second answer" in asked


def test_an_input_mapped_to_a_code_node_output_and_to_a_variable_reaches_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(
        api,
        user_prompt="C=${input.c}|V=${input.v}",
        inputs=[{"name": "c", "required": True}, {"name": "v", "required": True}],
    )
    code = {
        "language": "sh",
        "code": 'echo from code\necho \'{"ok": true, "vars": {"x": "a variable"}}\'',
    }
    pipeline = _flow(
        api, agent, "c = ${(Code).output}\nv = ${var.x}", before=[("code", "Code", code)]
    )
    _run(api, pipeline, task)
    asked = _asked(llm)
    assert asked.startswith("C=from code") and asked.endswith("|V=a variable")


def test_an_input_mapped_to_the_answer_of_an_agent_node_upstream_reaches_the_second_model_call(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    first = make_agent(
        api,
        name="First",
        user_prompt="Analyse ${input.t}",
        inputs=[{"name": "t", "required": True}],
    )
    second = make_agent(
        api,
        name="Second",
        user_prompt="Review: ${input.r}",
        inputs=[{"name": "r", "required": True}],
    )
    pipeline = _flow(
        api,
        second,
        "r = ${(Draft).output}",
        before=[("agent", "Draft", {"agent_id": first["id"], "inputs": "t = ${card.title}"})],
    )
    _run(api, pipeline, task)
    first_ask, second_ask = _asked(llm, 0), _asked(llm, 1)
    assert first_ask == f"Analyse {EPIC}"
    assert second_ask == f"Review: Answer to: {first_ask}"


# ── (d) several references, awkward text, size ───────────────────────


def test_a_mapping_value_with_several_references_and_text_around_them(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(api, user_prompt="[${input.e}]", inputs=[{"name": "e", "required": True}])
    _run(api, _flow(api, agent, "e = Epic: ${card.title} / ${card.body} / #${card.number}"), task)
    assert _asked(llm) == f"[Epic: {EPIC} / {BODY.strip()} / #{task['number']}]"


def test_a_body_with_quotes_dollar_signs_and_braces_is_not_interpreted_again(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(api, user_prompt="${input.b}", inputs=[{"name": "b", "required": True}])
    _run(api, _flow(api, agent, "b = ${card.body}"), task)
    assert _asked(llm) == BODY  # `${not.a.reference}` and the braces came through as text, once


def test_the_longest_body_the_api_allows_reaches_the_model_whole(
    api: TestClient, llm: FakeLlm
) -> None:
    line = 'quote " and ${not.a.reference} and $ {{x}} \n'
    body = (line * 400)[:10000]  # the API holds a body to 10,000 characters
    task = _task(api, body=body)
    agent = make_agent(api, user_prompt="${input.b}", inputs=[{"name": "b", "required": True}])
    _run(api, _flow(api, agent, "b = ${card.body}"), task)
    assert _asked(llm) == body.strip()


def test_a_body_beyond_the_limit_of_the_api_is_refused_when_it_is_saved(api: TestClient) -> None:
    response = api.post("/api/tasks", json={"title": EPIC, "body": "x" * 10001})
    assert response.status_code == 422 and "at most 10000 characters" in response.text


def test_a_card_too_large_for_a_run_is_refused_at_the_start_and_never_cut(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context, "CARD_LIMIT_BYTES", 2048)  # the real limit is 40 KiB
    task = _task(api, body="x" * 5000)
    agent = make_agent(api, user_prompt="${input.b}", inputs=[{"name": "b", "required": True}])
    pipeline = _flow(api, agent, "b = ${card.body}")
    llm.hits.clear()
    response = api.post(f"/api/tasks/{task['id']}/run", json={"pipeline_id": pipeline["id"]})
    assert response.status_code == 422
    assert "The artifact is too large to run" in response.json()["detail"]
    assert "holds 2 KiB" in response.json()["detail"]
    assert llm.completions() == []  # the model was not asked with half an epic


# ── (f) a mapping key the agent no longer declares ───────────────────


def test_a_mapped_key_the_agent_no_longer_declares_fails_the_run_with_the_reason(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(api, user_prompt="T=${input.t}", inputs=[{"name": "t", "required": True}])
    llm.hits.clear()
    run = _run(
        api, _flow(api, agent, "t = ${card.title}\nold = ${card.body}"), task, status="failed"
    )
    step = next(r for r in run["node_results"] if r["node_name"] == "Ask")
    assert step["reason"] == "input 'old' is not declared by the agent"
    assert llm.completions() == []  # nothing is ignored silently: the model is not asked


# ── (g) inside a stage of a pipeline started from a card ─────────────


def test_the_mapping_works_when_the_action_runs_in_a_stage_of_a_pipeline_started_from_a_card(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(
        api,
        user_prompt="${input.epic}",
        inputs=[{"name": "epic", "type": "artifact", "required": True}],
    )
    run = _run(
        api, _flow(api, agent, "epic = ${card.text}"), task
    )  # always started from the card, in a stage
    assert _asked(llm) == f"#{task['number']} {EPIC}\n\n{BODY}"
    asked_step = next(r for r in run["node_results"] if r["node_name"] == "Ask")
    assert (
        asked_step["stage_id"] and asked_step["action_id"]
    )  # the step belongs to a stage and its action
    assert run["status"] == "done"


# ── the migration: a field that clashes with a built-in name ─────────


def test_the_migration_renames_a_clashing_field_its_values_and_the_references_to_it(
    unmigrated_settings: Settings, at_revision: Callable[[str], Path]
) -> None:
    path = at_revision("0050")
    with sqlite3.connect(path) as db:
        for position, name in enumerate(("title", "urgency")):
            db.execute(
                "INSERT INTO artifact_fields (name, label, kind, position, integer_only, multiple) "
                "VALUES (?, ?, 'text', ?, 0, 0)",
                (name, name.title(), position),
            )
        db.execute(
            "INSERT INTO tasks (id, title, status, number, position, created_by, created_at, updated_at, "
            "field_values) VALUES ('t1', 'A', 'backlog', 1, 0, 'user', '2026-01-01', '2026-01-01', ?)",
            (json.dumps({"title": "kept", "urgency": "high"}),),
        )
        db.execute(
            "INSERT INTO graphs (id, name, status, created_at, updated_at, kind, slug) "
            "VALUES ('g1', 'Act', 'draft', '2026-01-01', '2026-01-01', 'action', 'act')"
        )
        db.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, created_at, updated_at, fail_enabled, config) "
            "VALUES ('n1', 'g1', 'http', 'Call', 0, 0, '2026-01-01', '2026-01-01', 0, ?)",
            (json.dumps({"url": "http://x/${card.title}/${card.urgency}/${card.titles}"}),),
        )
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as db:
        node = json.loads(db.execute("SELECT config FROM graph_nodes WHERE id='n1'").fetchone()[0])
        names = [r[0] for r in db.execute("SELECT name FROM artifact_fields ORDER BY position")]
        values = json.loads(
            db.execute("SELECT field_values FROM tasks WHERE id='t1'").fetchone()[0]
        )
    assert (
        node["url"] == "http://x/${card.title_field}/${card.urgency}/${card.titles}"
    )  # only the exact name
    assert names == ["title_field", "urgency"]
    assert values == {"title_field": "kept", "urgency": "high"}
    command.downgrade(cfg, "0050")
    with sqlite3.connect(path) as db:
        assert [r[0] for r in db.execute("SELECT name FROM artifact_fields ORDER BY position")] == [
            "title",
            "urgency",
        ]


# ── the resolved preview ─────────────────────────────────────────────


def test_the_preview_resolves_the_card_and_leaves_nodes_variables_and_secrets_as_placeholders(
    api: TestClient,
) -> None:
    task = _task(api)
    text = "A=${card.title} B=${card.number} C=${(Fetch).output} D=${var.x} E=${secret:TOKEN} F=${card.nope}"
    response = api.post(
        "/api/previews/references", json={"text": text, "card": str(task["number"])}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved"] == (
        f"A={EPIC} B={task['number']} C=\u2039output of Fetch\u203a D=\u2039variable x\u203a E=\u2039secret\u203a F=\u2039no field nope\u203a"
    )
    assert body["unresolved"] == ["card.nope"] and body["truncated"] is False


def test_the_preview_never_shows_a_secret_and_caps_a_long_result(api: TestClient) -> None:
    task = _task(api, body="y" * 5000)
    body = api.post(
        "/api/previews/references",
        json={"text": "${card.body} ${secret:TOKEN}", "card": task["id"]},
    ).json()
    assert body["truncated"] is True and len(body["resolved"]) <= 2001
    assert "TOKEN" not in body["resolved"]


def test_the_preview_of_an_unknown_card_is_not_found_and_needs_the_token(
    api: TestClient, migrated_settings: Settings
) -> None:
    assert (
        api.post("/api/previews/references", json={"text": "x", "card": "99999"}).status_code == 404
    )
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as anonymous:
        assert (
            anonymous.post("/api/previews/references", json={"text": "x", "card": "1"}).status_code
            == 401
        )


# ── the messages ─────────────────────────────────────────────────────


def test_an_undeclared_input_says_what_the_agent_declares_and_a_bad_name_says_the_rule(
    api: TestClient,
) -> None:
    agent = make_agent(
        api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}], publish=False
    )
    problems = api.put(
        f"/api/agents/{agent['id']}/draft",
        json={"user_prompt": "${input.nope} ${input.Bad}", "inputs": [{"name": "t"}]},
    ).json()
    text = json.dumps(problems)
    assert "${input.nope} is not a declared input (it declares: t)" in text
    assert "input names are lowercase letters, digits and _" in text
    empty = api.put(
        f"/api/agents/{agent['id']}/draft", json={"user_prompt": "${input.nope}", "inputs": []}
    ).json()
    assert (
        "this agent declares no inputs: declare one on the agent, then map it in the node"
        in json.dumps(empty)
    )


# ── a typo in a card reference is named when the setting is saved ────


def test_a_typo_in_a_card_reference_is_a_warning_at_save_that_names_the_known_names(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_fields(api, "test")
    agent = make_agent(api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}])
    pipeline = _flow(api, agent, "t = ${card.title}")
    action = api.get(
        f"{_url(pipeline)}"
    ).json()  # the pipeline; its action is the stage's definition
    del action
    graphs = api.get("/api/actions").json()
    answer = next(g for g in graphs if g["name"] == "Answer")
    nodes = api.get(_url(answer)).json()["nodes"]
    ask = next(n for n in nodes if n["name"] == "Ask")
    url = f"{_url(answer)}/nodes/{ask['id']}"

    def warnings(inputs: str) -> list[str]:
        response = api.patch(url, json={"config": {"inputs": inputs}})
        assert response.status_code == 200, response.text
        return response.json()["warnings"]  # type: ignore[no-any-return]

    assert warnings("t = ${card.title}") == []
    assert warnings("t = ${card.test}") == []
    assert warnings("t = ${card.titel}") == [
        '${card.titel}: the artifact has no field "titel" (it has: title, body, text, number, id, test)'
    ]

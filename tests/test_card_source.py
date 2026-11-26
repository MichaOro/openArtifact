"""The card as a source of the run (ADR-064): the built-in references, the reserved field names, and the input
mapping of an agent node end to end against the fake model (what the model RECEIVED is asserted, not the stored
mapping)."""

from __future__ import annotations

import json
import re
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


# ── (b) the artifact input: a source with a part, fixed by the definition ────────────────────────


def test_an_artifact_input_of_the_part_title_and_body_shows_number_title_and_body_to_the_model(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(
        api,
        user_prompt="Epic:\n${input.epic}",
        inputs=[{"name": "epic", "source": "artifact", "part": "title_body"}],
    )
    run = _run(api, _flow(api, agent, ""), task)  # the node maps nothing: the definition fixes it
    assert _asked(llm) == f"Epic:\n#{task['number']} {EPIC}\n\n{BODY}"
    detail = _step(api, run)["detail"]
    assert [(i["name"], i["origin"], i["part"], i["state"]) for i in detail["inputs"]] == [
        ("epic", "artifact", "title_body", "artifact")
    ]


def test_the_input_shape_is_normalised_and_an_old_artifact_type_is_read_as_the_source(
    api: TestClient,
) -> None:
    agent = make_agent(
        api,
        user_prompt="${input.epic} ${input.word}",
        inputs=[
            {"name": "epic", "type": "artifact"},  # the shape before the sources
            {"name": "word"},  # no source: a value
        ],
        publish=False,
    )
    inputs = api.get(f"/api/agents/{agent['id']}").json()["draft"]["inputs"]
    assert (inputs[0]["source"], inputs[0]["part"], inputs[0]["type"]) == (
        "artifact",
        "title_body",
        None,
    )
    assert (inputs[1]["source"], inputs[1]["type"], inputs[1]["part"]) == ("value", "string", None)
    odd = api.put(
        f"/api/agents/{agent['id']}/draft",
        json={
            "user_prompt": "${input.epic}",
            "inputs": [
                {
                    "name": "epic",
                    "source": "artifact",
                    "part": "body",
                    "required": True,
                    "default": "x",
                }
            ],
        },
    )
    assert odd.status_code == 200, (
        odd.text
    )  # required and default make no sense here: normalised away
    kept = odd.json()["draft"]["inputs"][0]
    assert (kept["part"], kept["required"], kept["default"]) == ("body", False, None)
    refused = api.put(
        f"/api/agents/{agent['id']}/draft",
        json={
            "user_prompt": "x",
            "inputs": [{"name": "epic", "source": "artifact", "part": "nope"}],
        },
    )
    assert refused.status_code == 422


def test_a_node_cannot_map_an_input_that_comes_from_the_artifact(api: TestClient) -> None:
    agent = make_agent(
        api,
        user_prompt="${input.epic} ${input.word}",
        inputs=[{"name": "epic", "source": "artifact", "part": "body"}, {"name": "word"}],
    )
    action = _post(api, "/api/actions", name="Answer")
    ask = _node(api, action, "agent", name="Ask", config={"agent_id": agent["id"]})
    refused = api.patch(
        f"{_url(action)}/nodes/{ask['id']}", json={"config": {"inputs": "epic = ${card.title}"}}
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == (
        "input 'epic' comes from the artifact and cannot be mapped in the action"
    )
    fine = api.patch(
        f"{_url(action)}/nodes/{ask['id']}", json={"config": {"inputs": "word = ${card.title}"}}
    )
    assert fine.status_code == 200, fine.text


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
        user_prompt="${input.epic} / ${input.who}",
        inputs=[{"name": "epic", "source": "artifact", "part": "title_body"}, {"name": "who"}],
    )
    run = _run(
        api, _flow(api, agent, "who = ${card.title}"), task
    )  # always started from the card, in a stage
    assert _asked(llm) == f"#{task['number']} {EPIC}\n\n{BODY} / {EPIC}"
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


# ── the resolved preview is gone ─────────────────────────────────────


def test_there_is_no_reference_preview_endpoint_any_more(api: TestClient) -> None:
    """The owner dropped the "Preview with card" and the resolved preview under fields (ADR-064 revised)."""
    for path in ("/api/previews/references", "/api/v1/previews/references"):
        assert api.post(path, json={"text": "x", "card": "1"}).status_code in (404, 405)


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


def test_the_node_dialog_is_told_about_a_typo_in_a_card_reference_of_the_mapping(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_fields(api, "test")
    agent = make_agent(api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}])
    _flow(api, agent, "t = ${card.titel}")
    answer = next(g for g in api.get("/api/actions").json() if g["name"] == "Answer")
    ask = next(n for n in api.get(_url(answer)).json()["nodes"] if n["name"] == "Ask")
    preview = api.post(
        f"/api/agents/{agent['id']}/preview", json={"source": "published", "node_id": ask["id"]}
    ).json()
    assert (
        '${card.titel}: the artifact has no field "titel" (it has: title, body, text, number, id, test)'
        in preview["problems"]
    )


# ── (h) every custom field is mappable, whatever its name and type ───────────────────────────────

LONG = "a_name_of_exactly_32_characters_"  # 32 characters
FIELDS: list[dict[str, Any]] = [
    {"name": "epic_url", "label": "Epic URL", "kind": "text"},
    {"name": "priority", "label": "Priority", "kind": "number"},
    {"name": "ratio", "label": "Ratio", "kind": "number"},
    {"name": "needs_review", "label": "Needs review", "kind": "boolean"},
    {"name": "repo", "label": "Repo", "kind": "choice", "options": ["api", "web"]},
    {"name": "v2_step_3", "label": "Step", "kind": "text"},
    {"name": LONG, "label": "Long", "kind": "text"},
]
VALUES: dict[str, Any] = {
    "epic_url": "https://example.test/e?a=1&b=${x}",
    "priority": 3,
    "ratio": 1.5,
    "needs_review": True,
    "repo": "web",
    "v2_step_3": "2026-12-31",  # a date is a text field: it stays as stored
    LONG: "long",
}


def _map(names: list[str]) -> tuple[str, list[dict[str, Any]], str]:
    # optional inputs: an input that is required and resolves to nothing fails the run by its own rule
    inputs = [{"name": f"i{n}", "required": False} for n in range(len(names))]
    mapping = "\n".join(f"i{n} = ${{card.{name}}}" for n, name in enumerate(names))
    prompt = "|".join(f"${{input.i{n}}}" for n in range(len(names)))
    return mapping, inputs, prompt


def _define_all(api: TestClient) -> None:
    assert len(LONG) == 32
    assert api.put("/api/artifact-fields", json={"fields": FIELDS}).status_code == 200


def test_every_kind_of_field_reaches_the_model_as_the_engine_writes_it_and_an_empty_one_is_empty_text(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_all(api)
    names = [f["name"] for f in FIELDS]
    mapping, inputs, prompt = _map(names)
    agent = make_agent(api, user_prompt=prompt, inputs=inputs)
    pipeline = _flow(api, agent, mapping)
    _run(api, pipeline, _task(api, **VALUES))
    assert _asked(llm) == "|".join(
        ["https://example.test/e?a=1&b=${x}", "3", "1.5", "true", "web", "2026-12-31", "long"]
    )
    # a card that filled none of them: every defined field is a key, empty, and the run does not fail
    _run(api, pipeline, _task(api, "Empty card", "b"))
    assert _asked(llm) == "|" * 6


def test_a_field_that_is_not_defined_is_refused_at_save_with_the_known_names(
    api: TestClient,
) -> None:
    _define_all(api)
    agent = make_agent(api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}])
    pipeline = _flow(api, agent, "t = ${card.nothing}")
    nodes = api.get(_url(next(a for a in api.get("/api/actions").json()))).json()["nodes"]
    ask = next(n for n in nodes if n["name"] == "Ask")
    action = next(a for a in api.get("/api/actions").json() if a["name"] == "Answer")
    saved = api.patch(
        f"{_url(action)}/nodes/{ask['id']}",
        json={"config": {"inputs": "t = ${card.nothing}", "agent_id": agent["id"]}},
    ).json()
    text = " ".join(saved["warnings"])
    assert 'the artifact has no field "nothing"' in text
    assert "epic_url" in text and "title" in text and LONG in text
    assert pipeline


def test_a_field_deleted_after_a_node_mapped_it_fails_the_run_naming_the_field(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_all(api)
    agent = make_agent(api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}])
    pipeline = _flow(api, agent, "t = ${card.epic_url}")
    task = _task(api, **VALUES)
    kept = [
        f for f in FIELDS if f["name"] != "epic_url"
    ]  # renaming is the same: the old name is gone
    assert api.put("/api/artifact-fields", json={"fields": kept}).status_code == 200
    run = _run(api, pipeline, task, status="failed")
    assert not llm.completions()
    step = _step(api, run)
    assert '${card.epic_url}: the artifact has no field "epic_url"' in str(step)


def test_the_node_dialog_names_a_field_deleted_after_the_mapping(api: TestClient) -> None:
    _define_all(api)
    agent = make_agent(api, user_prompt="${input.t}", inputs=[{"name": "t", "required": True}])
    _flow(api, agent, "t = ${card.epic_url}")
    action = next(a for a in api.get("/api/actions").json() if a["name"] == "Answer")
    ask = next(n for n in api.get(_url(action)).json()["nodes"] if n["name"] == "Ask")
    url = f"/api/agents/{agent['id']}/preview"
    body = {"source": "published", "node_id": ask["id"]}
    assert not [p for p in api.post(url, json=body).json()["problems"] if "card." in p]
    kept = [f for f in FIELDS if f["name"] != "epic_url"]
    api.put("/api/artifact-fields", json={"fields": kept}).raise_for_status()
    problems = api.post(url, json=body).json()["problems"]
    assert any('${card.epic_url}: the artifact has no field "epic_url"' in p for p in problems)


def test_custom_fields_work_in_conditions_edit_fields_and_the_code_context(
    api: TestClient, llm: FakeLlm
) -> None:
    _define_all(api)
    agent = make_agent(
        api,
        user_prompt="${input.a}|${input.b}|${input.c}",
        inputs=[{"name": n, "required": True} for n in "abc"],
    )
    code = {
        "language": "python",
        "code": "import json\nc = json.load(open('context.json'))['card']\n"
        "print(json.dumps({'ok': True, 'vars': {'seen': str(c['priority']) + c['repo']}}))",
    }
    pipeline = _flow(
        api,
        agent,
        "a = ${var.copied}\nb = ${var.seen}\nc = ${(Check).output}",
        before=[
            ("set", "Edit", {"fields": "copied = ${card.needs_review}-${card.ratio}"}),
            ("code", "Code", code),
        ],
    )
    action = next(a for a in api.get("/api/actions").json() if a["name"] == "Answer")
    graph = api.get(_url(action)).json()
    code_node = next(n for n in graph["nodes"] if n["name"] == "Code")
    ask = next(n for n in graph["nodes"] if n["name"] == "Ask")
    branch = _node(
        api,
        action,
        "if",
        name="Check",
        config={"left_1": "${card.priority}", "operator_1": "greater than", "right_1": "2"},
    )
    for edge in graph["edges"]:
        if edge["source_id"] == code_node["id"] and edge["target_id"] == ask["id"]:
            api.delete(f"{_url(action)}/edges/{edge['id']}")
    _connect(api, action, code_node, "pass", branch, "in")
    _connect(api, action, branch, "yes", ask, "in")
    _run(api, pipeline, _task(api, **VALUES))
    assert _asked(llm).startswith("true-1.5|3web|")


# ── (i) the card reaches the model only where the prompt put it ───────────────────────────────────


def _prompt_run(
    api: TestClient, llm: FakeLlm, prompt: str, inputs: list[dict[str, Any]], mapping: str
) -> str:
    agent = make_agent(api, user_prompt=prompt, inputs=inputs)
    _run(api, _flow(api, agent, mapping), _task(api))
    return _asked(llm)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("${input.x}", BODY),
        ("Read ${input.x}", f"Read {BODY}"),
        ("Lies ${input.x} und fasse zusammen", f"Lies {BODY} und fasse zusammen"),
    ],
)
def test_the_prompt_styles_put_the_card_exactly_where_the_author_wrote_it(
    api: TestClient, llm: FakeLlm, prompt: str, expected: str
) -> None:
    asked = _prompt_run(api, llm, prompt, [{"name": "x", "required": True}], "x = ${card.body}")
    assert asked == expected
    assert asked.count(EPIC) == 0 and len(llm.completions()) == 1


def test_title_and_body_in_separate_inputs_and_two_card_inputs_appear_once_each(
    api: TestClient, llm: FakeLlm
) -> None:
    asked = _prompt_run(
        api,
        llm,
        "Title: ${input.t}\nBody: ${input.b}",
        [{"name": "t", "required": True}, {"name": "b", "required": True}],
        "t = ${card.title}\nb = ${card.body}",
    )
    assert asked == f"Title: {EPIC}\nBody: {BODY}"
    assert asked.count(EPIC) == 1 and asked.count("Line one") == 1


def test_a_prompt_that_does_not_mention_the_card_gets_no_card_text(
    api: TestClient, llm: FakeLlm
) -> None:
    agent = make_agent(api, user_prompt="Say hello", system_prompt="Be brief", inputs=[])
    _run(api, _flow(api, agent, ""), _task(api))
    request = json.dumps(llm.completions()[-1]["json"])
    assert "Say hello" in request
    assert EPIC not in request and "Line one" not in request


def test_an_artifact_input_that_no_prompt_uses_is_not_sent_and_the_dialog_says_so(
    api: TestClient, llm: FakeLlm
) -> None:
    agent = make_agent(
        api,
        user_prompt="Say hello",
        inputs=[{"name": "epic", "source": "artifact", "part": "title_body"}],
    )
    pipeline = _flow(api, agent, "")
    _run(api, pipeline, _task(api))
    request = json.dumps(llm.completions()[-1]["json"])
    assert EPIC not in request and "Line one" not in request
    action = next(a for a in api.get("/api/actions").json() if a["name"] == "Answer")
    ask = next(n for n in api.get(_url(action)).json()["nodes"] if n["name"] == "Ask")
    calm = "Input epic comes from the artifact but no prompt uses it: the agent does not receive it"
    preview = api.post(
        f"/api/agents/{agent['id']}/preview", json={"source": "published", "node_id": ask["id"]}
    ).json()
    assert calm in preview["problems"]
    saved = api.patch(
        f"{_url(action)}/nodes/{ask['id']}", json={"config": {"user_prompt": "Say hello"}}
    ).json()
    assert calm in saved["warnings"]
    # used by a prompt of the node itself: no warning
    used = api.patch(
        f"{_url(action)}/nodes/{ask['id']}", json={"config": {"user_prompt": "Read ${input.epic}"}}
    ).json()
    assert calm not in used["warnings"]


# ── every part of the artifact, as the model receives it ─────────────────────────────────────────


def _parts_agent(api: TestClient, prompt: str, *inputs: tuple[str, str]) -> dict[str, Any]:
    return make_agent(
        api,
        user_prompt=prompt,
        inputs=[{"name": name, "source": "artifact", "part": part} for name, part in inputs],
    )


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ("title", EPIC),
        ("body", BODY),
        ("title_body", "#{n} " + EPIC + "\n\n" + BODY),
        ("number", "{n}"),
    ],
)
def test_every_part_of_the_card_reaches_the_model_as_the_definition_says(
    api: TestClient, llm: FakeLlm, part: str, expected: str
) -> None:
    task = _task(api)
    agent = _parts_agent(api, "[${input.x}]", ("x", part))
    _run(api, _flow(api, agent, ""), task)
    assert _asked(llm) == "[" + expected.replace("{n}", str(task["number"])) + "]"


def test_the_comments_part_delivers_every_comment_oldest_first_with_its_author(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    for text in ("first answer", "second\nanswer", "third answer"):
        assert api.post(f"/api/tasks/{task['id']}/comments", json={"body": text}).status_code == 201
    agent = _parts_agent(api, "Use the last two:\n${input.talk}", ("talk", "comments"))
    run = _run(api, _flow(api, agent, ""), task)
    asked = _asked(llm)
    blocks = asked.removeprefix("Use the last two:\n").split("\n\n")
    pattern = re.compile(r"^.+ \(\w+\), \d{4}-\d\d-\d\d \d\d:\d\d: ")
    assert len(blocks) == 3 and all(pattern.match(b) for b in blocks)
    assert [b.split(": ", 1)[1] for b in blocks] == [
        "first answer",
        "second\nanswer",
        "third answer",
    ]
    assert [i["state"] for i in _step(api, run)["detail"]["inputs"]] == ["artifact"]


def test_comments_beyond_the_limit_of_one_input_fail_the_run_naming_the_input(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    for _ in range(3):
        assert (
            api.post(f"/api/tasks/{task['id']}/comments", json={"body": "x" * 30000}).status_code
            == 201
        )
    agent = _parts_agent(api, "${input.talk}", ("talk", "comments"))
    run = _run(api, _flow(api, agent, ""), task, status="failed")
    reason = str(_step(api, run)["reason"])
    assert "input 'talk'" in reason and "limit for one input is 64 KiB" in reason
    assert not llm.completions()  # the model was not asked, nothing was cut


def test_two_inputs_of_the_artifact_in_one_prompt_appear_once_each(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = _parts_agent(api, "T=${input.t}|B=${input.b}", ("t", "title"), ("b", "body"))
    _run(api, _flow(api, agent, ""), task)
    asked = _asked(llm)
    assert asked == f"T={EPIC}|B={BODY}" and asked.count(EPIC) == 1


def test_an_artifact_input_without_an_artifact_fails_the_node_clearly() -> None:
    import asyncio

    from openartifact.agents.artifact_inputs import (
        NO_ARTIFACT,
        ArtifactInputError,
        artifact_values,
    )
    from openartifact.engine.context import RunView

    specs = [{"name": "epic", "source": "artifact", "part": "title_body"}]
    with pytest.raises(
        ArtifactInputError, match="needs an artifact, but the run has none"
    ) as caught:
        asyncio.run(artifact_values(specs, RunView(), None))
    assert str(caught.value) == NO_ARTIFACT == "this agent needs an artifact, but the run has none"


def test_a_stale_mapping_line_of_an_input_that_now_comes_from_the_artifact_is_ignored(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _task(api)
    agent = make_agent(api, user_prompt="${input.epic}", inputs=[{"name": "epic"}])
    pipeline = _flow(api, agent, "epic = something typed once")
    config = {
        "user_prompt": "${input.epic}",
        "inputs": [{"name": "epic", "source": "artifact", "part": "title"}],
    }
    assert api.put(f"/api/agents/{agent['id']}/draft", json=config).status_code == 200
    assert api.post(f"/api/agents/{agent['id']}/publish").status_code == 200
    run = _run(api, pipeline, task)
    assert _asked(llm) == EPIC  # the definition wins over the line left in the node
    states = [(i["name"], i["state"]) for i in _step(api, run)["detail"]["inputs"]]
    assert states == [
        ("epic", "artifact"),
        ("epic", "stale"),
    ]  # the line is shown as stale, never used


def test_the_quick_test_of_the_editor_shows_general_examples_for_the_parts(api: TestClient) -> None:
    agent = make_agent(
        api,
        user_prompt="${input.t} | ${input.b} | ${input.tb} | ${input.n} | ${input.c}",
        inputs=[
            {"name": "t", "source": "artifact", "part": "title"},
            {"name": "b", "source": "artifact", "part": "body"},
            {"name": "tb", "source": "artifact", "part": "title_body"},
            {"name": "n", "source": "artifact", "part": "number"},
            {"name": "c", "source": "artifact", "part": "comments"},
        ],
        publish=False,
    )
    shown = api.post(f"/api/agents/{agent['id']}/preview", json={"source": "draft"}).json()
    prompt = shown["user_prompt"]
    assert "Example artifact | This is the body of the example artifact. |" in prompt
    assert "#1 Example artifact\n\nThis is the body of the example artifact." in prompt
    assert "You (user), 2026-01-01 09:00: First comment" in prompt
    assert "Alice (user), 2026-01-01 09:05: Second comment" in prompt
    assert {i["state"] for i in shown["inputs"]} == {"sample"}


# ── the migration: the sources of the inputs ─────────────────────────────────────────────────────


def test_the_migration_writes_the_sources_and_takes_the_lines_of_artifact_inputs_out_of_the_nodes(
    unmigrated_settings: Settings, at_revision: Callable[[str], Path]
) -> None:
    path = at_revision("0051")
    old = {
        "user_prompt": "${input.text} ${input.word}",
        "inputs": [
            {
                "name": "text",
                "type": "artifact",
                "required": False,
                "default": None,
                "description": "",
            },
            {
                "name": "word",
                "type": "string",
                "required": True,
                "default": None,
                "description": "",
            },
            {"name": "n", "type": "number", "required": False, "default": 3, "description": ""},
        ],
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO agents (id, name, description, active, draft, published_number, version_seq, "
            "created_at, updated_at) VALUES ('a1', 'Sum', '', 1, ?, 2, 2, '2026-01-01', '2026-01-01')",
            (json.dumps(old),),
        )
        for number in (1, 2):
            db.execute(
                "INSERT INTO agent_versions (id, agent_id, number, config, published_via, published_at) "
                "VALUES (?, 'a1', ?, ?, 'publish', '2026-01-01')",
                (f"v{number}", number, json.dumps(old)),
            )
        db.execute(
            "INSERT INTO graphs (id, name, status, created_at, updated_at, kind, slug) "
            "VALUES ('g1', 'Act', 'draft', '2026-01-01', '2026-01-01', 'action', 'act')"
        )
        configs = {
            "n1": {"agent_id": "a1", "inputs": "text = ${card.text}\nword = ${card.title}"},
            "n2": {"agent_id": "a1", "inputs": "text = ${card.text}"},
            "n3": {"agent_id": "a1", "inputs": "input.word = x\nn = 4"},
            "n4": {"agent_id": "gone", "inputs": "text = kept"},
        }
        for node_id, config in configs.items():
            db.execute(
                "INSERT INTO graph_nodes (id, graph_id, kind, name, x, y, created_at, updated_at, "
                "fail_enabled, config) VALUES (?, 'g1', 'agent', ?, 0, 0, '2026-01-01', '2026-01-01', 0, ?)",
                (node_id, node_id, json.dumps(config)),
            )
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as db:
        draft = json.loads(db.execute("SELECT draft FROM agents WHERE id='a1'").fetchone()[0])
        versions = [
            json.loads(r[0])
            for r in db.execute("SELECT config FROM agent_versions ORDER BY number")
        ]
        nodes = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id, config FROM graph_nodes")}
    for config in (draft, *versions):
        by_name = {i["name"]: i for i in config["inputs"]}
        assert (by_name["text"]["source"], by_name["text"]["part"], by_name["text"]["type"]) == (
            "artifact",
            "title_body",
            None,
        )
        assert (
            by_name["word"]["source"],
            by_name["word"]["type"],
            by_name["word"]["required"],
        ) == (
            "value",
            "string",
            True,
        )
        assert by_name["n"]["default"] == 3 and by_name["n"]["source"] == "value"
    assert (
        nodes["n1"]["inputs"] == "word = ${card.title}"
    )  # the artifact line is gone, the rest stays
    assert "inputs" not in nodes["n2"]  # nothing left: the key goes
    assert nodes["n3"]["inputs"] == "input.word = x\nn = 4"
    assert nodes["n4"]["inputs"] == "text = kept"  # an agent that does not exist: untouched
    command.downgrade(cfg, "0051")
    with sqlite3.connect(path) as db:
        back = json.loads(db.execute("SELECT draft FROM agents WHERE id='a1'").fetchone()[0])
    assert {i["name"]: i["type"] for i in back["inputs"]} == {
        "text": "artifact",
        "word": "string",
        "n": "number",
    }
    assert all("source" not in i for i in back["inputs"])


def test_a_prompt_reads_the_fields_of_the_card_of_the_run_without_any_input(
    api: TestClient, llm: FakeLlm
) -> None:
    """${card.NAME} works in every prompt: each card brings its own value, the run takes the one of its card."""
    _define_fields(api, "test")
    agent = make_agent(
        api,
        user_prompt="Title=${card.title}|F=${card.test}",
        system_prompt="Card ${card.number}: ${card.test}",
        system_prompt_enabled=True,
        inputs=[],
    )
    pipeline = _flow(api, agent, "")
    _run(api, pipeline, _task(api, test="first"))
    _run(api, pipeline, _task(api, test="second"))
    first, second = llm.completions()[-2:]
    assert first["json"]["messages"][-1]["content"] == f"Title={EPIC}|F=first"
    assert second["json"]["messages"][-1]["content"] == f"Title={EPIC}|F=second"
    assert first["json"]["messages"][0]["content"].endswith(": first")
    assert second["json"]["messages"][0]["content"].endswith(": second")


def test_a_prompt_that_names_a_field_the_card_does_not_have_fails_the_run_with_the_reason(
    api: TestClient, llm: FakeLlm
) -> None:
    agent = make_agent(api, user_prompt="X=${card.nothing_here}", inputs=[])
    llm.hits.clear()
    run = _run(api, _flow(api, agent, ""), _task(api), status="failed")
    assert llm.completions() == []  # nothing is sent with half a prompt
    assert 'no field "nothing_here"' in _step(api, run)["reason"]

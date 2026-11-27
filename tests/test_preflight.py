"""The check before publishing (ADR-082): every kind of finding, and what the publish endpoint does with them.

The check reads the draft as data and runs nothing; the publish answers 409 with the findings unless the caller acknowledges them.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import connect, graph_url, kind_of, node, post
from tests.test_action_contract import INPUTS, OUTPUTS, _greeting_action, _stage_with


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"http_allow_private_networks": True})
    with TestClient(_create_app(settings)) as made:
        yield made


def _action(client: TestClient, *url_texts: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """An action trigger -> one HTTP node per text (the text is the URL) -> output."""
    action = post(client, "/api/actions", name=f"A {uuid.uuid4().hex[:6]}")
    trigger, output = kind_of(client, action, "trigger"), kind_of(client, action, "output")
    for edge in client.get(graph_url(action)).json()["edges"]:
        client.delete(f"{graph_url(action)}/edges/{edge['id']}")
    previous, port, made = trigger, "out", []
    for i, text in enumerate(url_texts):
        item = node(client, action, "http", name=f"Call {i + 1}", config={"url": text})
        connect(client, action, previous, port, item, "in")
        previous, port = item, "pass"
        made.append(item)
    connect(client, action, previous, port, output, "pass")
    return action, made


def _findings(
    client: TestClient, graph: dict[str, Any], kind: str = "actions"
) -> list[dict[str, Any]]:
    response = client.get(f"/api/{kind}/{graph['id']}/check")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] + body["warnings"] == len(body["findings"])
    found = body["findings"]
    assert isinstance(found, list)
    return found


def _codes(findings: list[dict[str, Any]]) -> list[str]:
    return [f["code"] for f in findings]


def test_a_clean_draft_has_no_findings(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/a", "http://example.test/${card.title}")
    assert _findings(client, action) == []


def test_a_secret_that_does_not_exist_is_an_error_naming_the_node(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/${secret:NOPE}")
    found = _findings(client, action)
    assert [(f["level"], f["code"], f["node_name"]) for f in found] == [
        ("error", "secret_missing", "Call 1")
    ]
    assert found[0]["message"] == "the secret 'NOPE' does not exist"


def test_a_card_field_the_artifact_does_not_have_is_an_error(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/${card.nothing}")
    found = _findings(client, action)
    assert _codes(found) == ["card_field_missing"]
    assert "the artifact has no field 'nothing'" in found[0]["message"]


def test_a_reference_to_a_node_that_is_gone_is_an_error_without_an_id_in_the_message(
    client: TestClient,
) -> None:
    gone = str(uuid.uuid4())
    action, _ = _action(client, f"http://example.test/${{node:{gone}.output}}")
    found = _findings(client, action)
    assert _codes(found) == ["node_missing"]
    assert "does not exist any more" in found[0]["message"]


def test_two_nodes_of_one_name_make_a_name_reference_an_error(client: TestClient) -> None:
    action, made = _action(client, "http://example.test/a", "http://example.test/b")
    client.patch(f"{graph_url(action)}/nodes/{made[1]['id']}", json={"name": "Call 1"})
    third = node(
        client,
        action,
        "http",
        name="Reader",
        config={"url": "http://example.test/${(Call 1).output}"},
    )
    connect(client, action, kind_of(client, action, "trigger"), "out", third, "in")
    found = _findings(client, action)
    assert "name_ambiguous" in _codes(found)
    ambiguous = next(f for f in found if f["code"] == "name_ambiguous")
    assert (
        ambiguous["node_name"] == "Reader" and "2 nodes are called 'Call_1'" in ambiguous["message"]
    )


def test_a_name_that_no_node_has_is_an_error(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/${(Nobody).output}")
    assert _codes(_findings(client, action)) == ["node_missing"]


def test_a_node_after_this_one_is_a_warning_it_may_not_have_run(client: TestClient) -> None:
    action, made = _action(client, "http://example.test/a", "http://example.test/b")
    reference = f"http://example.test/${{node:{made[1]['id']}.output}}"
    client.patch(f"{graph_url(action)}/nodes/{made[0]['id']}", json={"config": {"url": reference}})
    found = _findings(client, action)
    assert [(f["level"], f["code"]) for f in found] == [("warning", "node_not_before")]
    assert "'Call 2' is not in front of this node on every path" in found[0]["message"]


def test_an_input_the_graph_does_not_declare_is_an_error_and_a_declared_one_is_fine(
    client: TestClient,
) -> None:
    action, _ = _action(client, "http://example.test/${input.who}")
    found = _findings(client, action)
    assert _codes(found) == ["input_missing"]
    assert "declares no input 'who' (its inputs: none)" in found[0]["message"]
    trigger = kind_of(client, action, "trigger")
    client.patch(
        f"{graph_url(action)}/nodes/{trigger['id']}",
        json={"config": {"inputs": [{"name": "who", "type": "text", "required": False}]}},
    )
    assert _findings(client, action) == []


def test_a_variable_no_edit_fields_node_sets_is_a_warning_unless_a_script_might(
    client: TestClient,
) -> None:
    action, _ = _action(client, "http://example.test/${var.token}")
    assert [(f["level"], f["code"]) for f in _findings(client, action)] == [
        ("warning", "variable_unknown")
    ]
    script = node(client, action, "code", name="Script", config={"language": "sh", "code": "true"})
    connect(client, action, kind_of(client, action, "trigger"), "out", script, "in")
    assert _findings(client, action) == []  # a script may set it: the check cannot tell


def test_a_required_input_without_a_value_is_an_error_at_the_node_that_runs_the_action(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, INPUTS, OUTPUTS)
    pipeline, placed = _stage_with(client, definition, [{"times": "3"}])
    found = _findings(client, pipeline, "pipelines")
    assert [(f["level"], f["code"], f["node_name"]) for f in found] == [
        ("error", "input_not_given", "Greet")
    ]
    assert found[0]["node_id"] == placed[0]["id"]
    assert "needs the input 'who' (required)" in found[0]["message"]


def test_an_input_with_a_default_needs_no_value_and_an_unknown_one_is_a_warning(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, INPUTS, OUTPUTS)
    pipeline, _ = _stage_with(client, definition, [{"who": "Ann", "other": "x"}])
    found = _findings(client, pipeline, "pipelines")
    assert [(f["level"], f["code"]) for f in found] == [("warning", "input_unknown")]
    assert "gives a value to 'other', which the action does not declare" in found[0]["message"]


def test_reading_an_output_the_action_does_not_declare_is_an_error(client: TestClient) -> None:
    definition = _greeting_action(client, INPUTS, OUTPUTS)
    pipeline, placed = _stage_with(client, definition, [{"who": "Ann"}, {"who": "Bob"}])
    client.patch(
        f"{graph_url(pipeline)}/nodes/{placed[1]['id']}",
        json={"config": {"input_values": {"who": f"${{node:{placed[0]['id']}.data.nothing}}"}}},
    )
    found = _findings(client, pipeline, "pipelines")
    assert [(f["level"], f["code"]) for f in found] == [("error", "output_missing")]
    assert "'Greet' has no output 'nothing' (its outputs: count, greeting)" in found[0]["message"]


def test_reading_the_result_of_an_action_without_a_contract_is_an_error(client: TestClient) -> None:
    plain = _greeting_action(client, None, None, fields="greeting = plain")
    pipeline, placed = _stage_with(client, plain, [{}, {}])
    client.patch(
        f"{graph_url(pipeline)}/nodes/{placed[1]['id']}",
        json={"config": {"input_values": {"x": f"${{node:{placed[0]['id']}.data.x}}"}}},
    )
    found = _findings(client, pipeline, "pipelines")
    # the error first; the mapped 'x' is also told as unknown, because that action declares no inputs
    assert _codes(found) == ["placement_no_contract", "input_unknown"]


def test_the_findings_come_errors_first(client: TestClient) -> None:
    action, made = _action(
        client, "http://example.test/${var.token}", "http://example.test/${card.nothing}"
    )
    assert [f["level"] for f in _findings(client, action)] == ["error", "warning"]
    assert made  # both nodes exist


# ── the publish endpoint ─────────────────────────────────────────────


def test_publishing_over_findings_is_refused_with_the_findings_until_acknowledged(
    client: TestClient,
) -> None:
    action, _ = _action(client, "http://example.test/${card.nothing}")
    refused = client.post(f"/api/actions/{action['id']}/publish")
    assert refused.status_code == 409
    body = refused.json()
    assert body["code"] == "findings"
    assert body["detail"].startswith("The check found 1 thing(s) to look at before publishing")
    assert [f["code"] for f in body["findings"]] == ["card_field_missing"]
    assert client.get(f"/api/actions/{action['id']}").json()["graph"]["published_version"] is None
    accepted = client.post(f"/api/actions/{action['id']}/publish", json={"acknowledge": True})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["version"]["number"] == 1


def test_a_clean_draft_publishes_without_acknowledging(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/${card.title}")
    assert client.post(f"/api/actions/{action['id']}/publish").status_code == 200


def test_publishing_what_did_not_change_says_so_even_with_findings(client: TestClient) -> None:
    action, _ = _action(client, "http://example.test/${card.nothing}")
    client.post(f"/api/actions/{action['id']}/publish", json={"acknowledge": True})
    again = client.post(f"/api/actions/{action['id']}/publish")
    assert again.status_code == 409 and "Nothing changed since version 1" in again.json()["detail"]


def test_saving_a_draft_is_never_checked(client: TestClient) -> None:
    action, made = _action(client, "http://example.test/a")
    saved = client.patch(
        f"{graph_url(action)}/nodes/{made[0]['id']}",
        json={"config": {"url": "http://example.test/${secret:NOPE}/${(Nobody).output}"}},
    )
    assert saved.status_code == 200  # the draft may be wrong: only what is published runs


def test_a_pipeline_node_is_checked_like_an_action_node(client: TestClient) -> None:
    inner = post(client, "/api/pipelines", name="Inner check")
    client.patch(
        f"{graph_url(inner)}/nodes/{kind_of(client, inner, 'trigger')['id']}",
        json={"config": {"inputs": [{"name": "who", "type": "text", "required": True}]}},
    ).raise_for_status()
    outer = post(client, "/api/pipelines", name="Outer check")
    caller = node(client, outer, "pipeline", name="Call")
    connect(client, outer, kind_of(client, outer, "trigger"), "out", caller, "in")
    client.patch(
        f"{graph_url(outer)}/nodes/{caller['id']}", json={"definition_id": inner["id"]}
    ).raise_for_status()
    found = _findings(client, outer, "pipelines")
    assert [(f["level"], f["code"], f["node_id"]) for f in found] == [
        ("error", "input_not_given", caller["id"])
    ]
    client.patch(
        f"{graph_url(outer)}/nodes/{caller['id']}",
        json={"config": {"input_values": {"who": "Ann", "extra": "x"}}},
    ).raise_for_status()
    assert [(f["level"], f["code"]) for f in _findings(client, outer, "pipelines")] == [
        ("warning", "input_unknown")
    ]

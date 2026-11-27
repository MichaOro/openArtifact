"""The contract of the version that runs (ADR-083 addendum 2).

The inputs and outputs an action shows in the pipelines that use it are those of the version an execution runs: the published one (ADR-070),
not the draft that may be half edited. They change when the action is published, or come back when its draft is discarded; an action that
was never published runs its draft, so its draft contract is what is shown then. The check of a pipeline reads the same contract, and
publishing an action whose contract changes warns about the pipelines that use it.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import graph_url, kind_of
from tests.test_action_contract import _declare, _greeting_action, _run, _stage_with


@pytest.fixture
def client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(update={"http_allow_private_networks": True})
    with TestClient(_create_app(settings)) as made:
        yield made


WHO = {"name": "who", "type": "text", "required": True}
TIMES = {"name": "times", "type": "number", "required": False, "default": "2"}
OUT_GREETING = {"name": "greeting", "type": "text", "value": "${var.greeting}"}


def _contract(client: TestClient, action: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"/api/actions/{action['id']}/contract")
    assert response.status_code == 200, response.text
    answer = response.json()
    assert isinstance(answer, dict)
    return answer


def _names(contract: dict[str, Any], key: str) -> list[str]:
    return [spec["name"] for spec in contract[key]]


def _publish(client: TestClient, graph: dict[str, Any], kind: str = "actions", **body: Any) -> Any:
    return client.post(f"/api/{kind}/{graph['id']}/publish", json={"acknowledge": True, **body})


def test_an_action_that_was_never_published_runs_its_draft_so_its_draft_contract_is_shown(
    client: TestClient,
) -> None:
    action = _greeting_action(client, [WHO], [OUT_GREETING])
    found = _contract(client, action)
    assert (found["version"], found["running"], found["draft_changed"]) == (None, "draft", False)
    assert _names(found, "inputs") == ["who"] and _names(found, "outputs") == ["greeting"]


def test_while_the_draft_has_changes_the_contract_is_the_published_one_until_publish_and_again_after_discard(
    client: TestClient,
) -> None:
    action = _greeting_action(client, [WHO], [OUT_GREETING])
    assert _publish(client, action).status_code == 200
    assert _names(_contract(client, action), "inputs") == ["who"]
    # the draft is edited: a new input is typed in the Trigger
    _declare(client, action, [WHO, TIMES], None)
    during = _contract(client, action)
    assert _names(during, "inputs") == ["who"], "the pipelines keep seeing what runs, not the draft"
    assert (during["version"], during["running"], during["draft_changed"]) == (1, "published", True)
    # Publish: the new contract appears
    assert _publish(client, action).status_code == 200
    after = _contract(client, action)
    assert _names(after, "inputs") == ["who", "times"]
    assert (after["version"], after["draft_changed"]) == (2, False)
    # edit again and throw the change away: the published contract is there again
    _declare(client, action, [WHO], None)
    assert _names(_contract(client, action), "inputs") == ["who", "times"]
    assert client.post(f"/api/actions/{action['id']}/draft/discard").status_code == 200
    again = _contract(client, action)
    assert _names(again, "inputs") == ["who", "times"] and again["draft_changed"] is False


def test_the_contract_of_a_pipeline_is_read_the_same_way(client: TestClient) -> None:
    pipeline = client.post("/api/pipelines", json={"name": "Called"}).json()
    complete = kind_of(client, pipeline, "complete")
    client.patch(
        f"{graph_url(pipeline)}/nodes/{complete['id']}",
        json={"config": {"outputs": [{"name": "answer", "type": "text", "value": "x"}]}},
    ).raise_for_status()
    found = client.get(f"/api/pipelines/{pipeline['id']}/contract").json()
    assert (found["kind"], found["running"], _names(found, "outputs")) == (
        "pipeline",
        "draft",
        ["answer"],
    )
    assert client.get("/api/actions/does-not-exist/contract").status_code == 404


def _codes(client: TestClient, graph: dict[str, Any], kind: str) -> dict[str, list[str]]:
    found = client.get(f"/api/{kind}/{graph['id']}/check").json()["findings"]
    out: dict[str, list[str]] = {}
    for item in found:
        out.setdefault(item["code"], []).append(item["message"])
    return out


def test_a_pipeline_is_checked_against_the_published_contract_not_the_draft_of_its_action(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, [WHO], [OUT_GREETING])
    assert _publish(client, definition).status_code == 200
    # the draft of the action gets an input 'times'; a pipeline maps it already (typed ahead)
    _declare(client, definition, [WHO, TIMES], None)
    pipeline, _ = _stage_with(client, definition, [{"who": "Ann", "times": "3"}])
    during = _codes(client, pipeline, "pipelines")
    assert "input_unknown" in during, (
        "'times' is not in the version that runs: reported while the action is a draft"
    )
    assert any("times" in text for text in during["input_unknown"])
    # published: the contract has it, the finding is gone
    assert _publish(client, definition).status_code == 200
    assert "input_unknown" not in _codes(client, pipeline, "pipelines")


def test_a_pipeline_that_maps_an_input_a_later_version_removed_is_reported(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, [WHO, TIMES], [OUT_GREETING])
    assert _publish(client, definition).status_code == 200
    pipeline, _ = _stage_with(client, definition, [{"who": "Ann", "times": "3"}])
    assert "input_unknown" not in _codes(client, pipeline, "pipelines")
    _declare(client, definition, [WHO], None)
    assert _publish(client, definition).status_code == 200
    found = _codes(client, pipeline, "pipelines")
    assert any("times" in text for text in found["input_unknown"]), found


def test_publishing_an_action_whose_contract_changes_warns_about_the_pipelines_that_use_it(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, [WHO, TIMES], [OUT_GREETING])
    assert _publish(client, definition).status_code == 200
    pipeline, _ = _stage_with(client, definition, [{"who": "Ann", "times": "3"}])
    # nothing changes: no warning
    assert not [c for c in _codes(client, definition, "actions") if c.startswith("contract_")]
    # the next version drops 'times', adds a required 'topic' and drops the output
    _declare(client, definition, [WHO, {"name": "topic", "type": "text", "required": True}], [])
    found = _codes(client, definition, "actions")
    assert any(
        pipeline["name"] in text and "'times'" in text for text in found["contract_input_removed"]
    ), found
    assert any(
        pipeline["name"] in text and "'topic'" in text for text in found["contract_input_new"]
    ), found
    assert any(
        pipeline["name"] in text and "greeting" in text for text in found["contract_output_removed"]
    ), found
    levels = {
        f["level"]
        for f in client.get(f"/api/actions/{definition['id']}/check").json()["findings"]
        if f["code"].startswith("contract_")
    }
    assert levels == {"warning"}, "the owner decides: a warning, never an error"
    # the publish asks first (findings), and goes through once they are acknowledged
    refused = client.post(f"/api/actions/{definition['id']}/publish")
    assert refused.status_code == 409 and refused.json().get("code") == "findings"
    assert _publish(client, definition).status_code == 200


def test_an_action_that_was_never_published_says_nothing_about_its_users(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, [WHO], [OUT_GREETING])
    _stage_with(client, definition, [{"who": "Ann"}])
    assert not [c for c in _codes(client, definition, "actions") if c.startswith("contract_")]


def test_a_run_uses_the_published_contract_so_a_new_required_input_of_the_draft_does_not_stop_it(
    client: TestClient,
) -> None:
    definition = _greeting_action(client, [WHO, TIMES], [OUT_GREETING])
    assert _publish(client, definition).status_code == 200
    pipeline, placed = _stage_with(client, definition, [{"who": "Ann"}])
    _declare(
        client, definition, [WHO, TIMES, {"name": "topic", "type": "text", "required": True}], None
    )  # only the draft
    nodes = _run(client, pipeline)["context"][
        "nodes"
    ]  # done: 'topic' is required by the draft, not by what runs
    by_id = {entry["id"]: entry for entry in nodes.values() if "id" in entry}
    assert by_id[placed[0]["id"]]["data"]["greeting"].startswith("Hello Ann")
    # after the publication the same pipeline fails with the plain reason of a required input without a value
    assert _publish(client, definition).status_code == 200
    failed = _run(client, pipeline, status="failed")
    assert "topic" in str(failed.get("note") or failed), failed

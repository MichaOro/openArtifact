"""The body of an artifact with its ${card.x} filled in where it is read (ADR-064 addendum): the single read, the
list of the board, the events of a change, the note when it is saved, the MCP read and the card a run starts with
(what the model RECEIVED is asserted)."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.artifact_fields.body import ELLIPSIS, PREVIEW_WORDS
from openartifact.config import Settings
from tests.agent_support import HEADERS as AGENT_HEADERS
from tests.agent_support import SECURE, FakeLlm, fake_llm, make_agent, make_provider
from tests.test_card_source import _asked, _flow, _run

FIELDS = [
    {"name": "test", "label": "Test", "kind": "text"},
    {"name": "priority", "label": "Priority", "kind": "number"},
    {"name": "needs_review", "label": "Review", "kind": "boolean"},
]


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings.model_copy(update=SECURE))) as client:
        client.headers.update(AGENT_HEADERS)
        client.put("/api/artifact-fields", json={"fields": FIELDS}).raise_for_status()
        yield client


@pytest.fixture
def llm(api: TestClient) -> Iterator[FakeLlm]:
    with fake_llm() as server:
        make_provider(api, server)
        yield server


def _card(
    api: TestClient, body: str, title: str = "Der letzte Leuchtturm", **fields: Any
) -> dict[str, Any]:
    response = api.post("/api/tasks", json={"title": title, "body": body, "fields": fields})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


BODY = "Elias: ${card.test} (${card.priority}, review ${card.needs_review}) of ${card.title}."


def test_a_single_read_keeps_the_original_and_adds_the_filled_in_text(api: TestClient) -> None:
    made = _card(api, BODY, test="Als Elias erwachte", priority=3, needs_review=True)
    got = api.get(f"/api/tasks/{made['id']}").json()
    assert got["body"] == BODY  # the original, never changed
    assert got["fields"] == {"test": "Als Elias erwachte", "priority": 3, "needs_review": True}
    assert (
        got["body_resolved"]
        == "Elias: Als Elias erwachte (3, review true) of Der letzte Leuchtturm."
    )
    assert got["preview"] is None  # the list carries the preview


def test_the_integration_api_returns_the_same(api: TestClient) -> None:
    made = _card(api, "${card.title}!")
    by_number = api.get(f"/api/v1/artifacts/{made['number']}").json()
    assert (
        by_number["body"] == "${card.title}!"
        and by_number["body_resolved"] == "Der letzte Leuchtturm!"
    )


def test_a_body_without_a_reference_has_no_resolved_text_and_no_preview(api: TestClient) -> None:
    made = _card(api, "just words " * 100)
    got = api.get(f"/api/tasks/{made['id']}").json()
    listed = next(t for t in api.get("/api/tasks").json() if t["id"] == made["id"])
    assert got["body_resolved"] is None and listed["preview"] is None


def test_a_reference_that_names_nothing_is_not_called_resolved(api: TestClient) -> None:
    made = _card(api, "see ${card.nope} and ${card.body}")
    assert api.get(f"/api/tasks/{made['id']}").json()["body_resolved"] is None


def test_the_list_carries_the_preview_of_a_body_with_references_and_not_the_whole_text(
    api: TestClient,
) -> None:
    long = "${card.title} " + " ".join(f"w{i}" for i in range(400))
    made = _card(api, long)
    listed = next(t for t in api.get("/api/tasks").json() if t["id"] == made["id"])
    assert listed["body"] == long and listed["body_resolved"] is None
    words = listed["preview"].removesuffix(ELLIPSIS).split()
    assert len(words) == PREVIEW_WORDS and listed["preview"].endswith(ELLIPSIS)
    assert words[:3] == ["Der", "letzte", "Leuchtturm"]


def test_a_field_that_has_no_value_reads_as_its_default_or_empty(api: TestClient) -> None:
    made = _card(api, "[${card.test}] [${card.priority}]")
    assert api.get(f"/api/tasks/{made['id']}").json()["body_resolved"] == "[] []"


def test_saving_names_a_reference_that_names_nothing_but_saves(api: TestClient) -> None:
    made = _card(api, "plain")
    response = api.patch(
        f"/api/tasks/{made['id']}", json={"body": "a ${card.nope} b ${card.body} ${card.test}"}
    )
    assert response.status_code == 200
    assert response.json()["warnings"] == [
        "${card.nope}: the artifact has no field 'nope'",
        "${card.body}: a body cannot contain itself, so this is shown as written",
    ]
    again = api.get(f"/api/tasks/{made['id']}").json()
    assert again["body"] == "a ${card.nope} b ${card.body} ${card.test}"  # saved as written
    assert again["warnings"] == []  # a note about the save, not part of the artifact
    created = api.post("/api/tasks", json={"title": "t", "body": "${card.nope}"}).json()
    assert created["warnings"] == ["${card.nope}: the artifact has no field 'nope'"]


def test_the_events_of_a_change_carry_the_filled_in_text_and_no_warnings(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    client.put("/api/artifact-fields", json={"fields": FIELDS}).raise_for_status()
    made = client.post(
        "/api/tasks", json={"title": "T", "body": "${card.test}/${card.nope}"}
    ).json()
    published.clear()
    client.patch(f"/api/tasks/{made['id']}", json={"fields": {"test": "one"}})
    name, payload = published[0]
    assert name == "task.updated"
    assert (
        payload["body_resolved"] == "one/${card.nope}" and payload["preview"] == "one/${card.nope}"
    )
    assert "warnings" not in payload and payload["body"] == "${card.test}/${card.nope}"


# ── a run reads the finished text ───────────────────────────────────


def test_an_agent_reads_the_finished_body_of_the_card(api: TestClient, llm: FakeLlm) -> None:
    task = _card(api, "Summarise ${card.test} by ${card.title}", test="the lighthouse tale")
    agent = make_agent(
        api,
        user_prompt="Read: ${input.body}",
        inputs=[{"name": "body", "source": "artifact", "part": "body"}],
    )
    run = _run(api, _flow(api, agent, ""), task)
    assert run["status"] == "done"
    assert _asked(llm) == "Read: Summarise the lighthouse tale by Der letzte Leuchtturm"


def test_the_title_and_body_part_and_a_mapped_card_body_are_the_finished_text_too(
    api: TestClient, llm: FakeLlm
) -> None:
    task = _card(api, "Fill ${card.test}", test="X")
    agent = make_agent(
        api,
        user_prompt="A ${input.both} B ${input.mapped}",
        inputs=[
            {"name": "both", "source": "artifact", "part": "title_body"},
            {"name": "mapped", "source": "value", "type": "string"},
        ],
    )
    _run(api, _flow(api, agent, "mapped = ${card.body}"), task)
    assert _asked(llm) == f"A #{task['number']} Der letzte Leuchtturm\n\nFill X B Fill X"


def test_a_title_is_never_filled_in(api: TestClient, llm: FakeLlm) -> None:
    task = _card(api, "b", title="About ${card.test}", test="T")
    agent = make_agent(
        api,
        user_prompt="${input.title}",
        inputs=[{"name": "title", "source": "artifact", "part": "title"}],
    )
    _run(api, _flow(api, agent, ""), task)
    assert _asked(llm) == "About ${card.test}"

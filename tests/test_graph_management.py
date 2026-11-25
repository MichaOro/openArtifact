"""What the management pages (ADR-069) read of pipelines and actions: a description, tags, the number of nodes, a search by text
or tag, and where a definition is used."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import build_pipeline, graph_url, link, post


def test_description_and_tags_are_set_when_made_changed_and_tidied(client: TestClient) -> None:
    made = post(
        client,
        "/api/actions",
        name="Gap",
        description="  Finds gaps in epics.  ",
        tags=["Epic", " analysis ", "epic", "", "Quality"],
    )
    assert made["description"] == "Finds gaps in epics."
    assert made["tags"] == ["Epic", "analysis", "Quality"], (
        "trimmed, no empty ones, no repeat in another case"
    )
    plain = post(client, "/api/pipelines", name="Flow")
    assert (plain["description"], plain["tags"]) == ("", [])
    changed = client.patch(graph_url(made), json={"description": "Other", "tags": ["a"]})
    assert changed.status_code == 200
    assert (changed.json()["description"], changed.json()["tags"]) == ("Other", ["a"])
    only_tags = client.patch(graph_url(made), json={"tags": []}).json()
    assert (only_tags["description"], only_tags["tags"]) == ("Other", []), (
        "a field that is left out keeps its value"
    )
    assert client.patch(graph_url(made), json={}).status_code == 422


def test_wrong_description_or_tags_are_refused(client: TestClient) -> None:
    for body in (
        {"name": "x", "description": "d" * 1001},
        {"name": "x", "tags": ["t" * 33]},
        {"name": "x", "tags": [f"t{i}" for i in range(21)]},
    ):
        assert client.post("/api/actions", json=body).status_code == 422, body


def test_the_list_counts_nodes_and_searches_by_text_and_tag(client: TestClient) -> None:
    post(client, "/api/actions", name="Gap hunter", description="Looks at epics", tags=["epic"])
    post(client, "/api/actions", name="Mailer", tags=["mail", "EPIC-x"])
    post(client, "/api/actions", name="Other", tags=["misc"])
    listed = client.get("/api/actions").json()
    assert all(a["node_count"] == 2 for a in listed), "a new action has its trigger and its output"

    def names(params: dict[str, str]) -> list[str]:
        return sorted(a["name"] for a in client.get("/api/actions", params=params).json())

    assert names({"q": "EPIC"}) == ["Gap hunter", "Mailer"], "name, description or a tag, any case"
    assert names({"q": "mail"}) == ["Mailer"]
    assert names({"tag": "Epic"}) == ["Gap hunter"], "a tag exactly, any case"
    assert names({"tag": "epic", "q": "gap"}) == ["Gap hunter"]
    assert names({"q": "nothing"}) == []


def test_an_action_says_where_it_is_used(client: TestClient) -> None:
    action = post(client, "/api/actions", name="Judge")
    assert client.get(f"{graph_url(action)}/uses").json() == {
        "uses": [],
        "artifacts": None,
        "executions": None,
    }
    pipeline = build_pipeline(client, stages=1, name="Flow", stage_name="Review")
    link(client, pipeline, pipeline["stages"][0][1], action)
    uses = client.get(f"{graph_url(action)}/uses").json()["uses"]
    assert uses == [
        {"kind": "stage", "name": "Flow", "href": "/pipelines/flow", "detail": "Review"}
    ]
    guard = post(client, "/api/actions", name="Watcher", purpose="guard")
    assert client.post(
        "/api/guards",
        json={
            "name": "Health",
            "trigger": {"type": "event", "events": ["enter"]},
            "when": {"type": "group", "mode": "all", "items": []},
            "consequence": "run_action",
            "action_id": guard["id"],
        },
    ).status_code in (200, 201)
    found: list[dict[str, Any]] = client.get(f"{graph_url(guard)}/uses").json()["uses"]
    assert found == [{"kind": "guard", "name": "Health", "href": "/guards", "detail": ""}]


def test_a_pipeline_says_who_calls_it_and_how_much_it_was_used(client: TestClient) -> None:
    inner = post(client, "/api/pipelines", name="Inner")
    nothing = client.get(f"{graph_url(inner)}/uses").json()
    assert nothing == {"uses": [], "artifacts": 0, "executions": 0}
    outer = post(client, "/api/pipelines", name="Outer")
    called = post(client, f"{graph_url(outer)}/nodes", kind="pipeline")
    link(client, outer, called, inner)
    uses = client.get(f"{graph_url(inner)}/uses").json()["uses"]
    assert uses == [{"kind": "pipeline", "name": "Outer", "href": "/pipelines/outer", "detail": ""}]
    assert client.get("/api/pipelines/unknown/uses").status_code == 404

"""The personal settings (ADR-062): what exists and its default is the form manifest; the API reads and writes it; the
setting *Mark resolved references* decides whether the server sends marked segments with an artifact."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact import personal_settings
from openartifact.api.settings import PersonalSettingsRead, PersonalSettingsWrite
from openartifact.ui.forms import FORMS

URL = "/api/settings/personal"


def test_the_models_and_the_manifest_declare_the_same_settings() -> None:
    manifest = personal_settings.defaults()
    assert set(PersonalSettingsRead.model_fields) == set(manifest)
    assert set(PersonalSettingsWrite.model_fields) == set(manifest)
    # the one place that declares a default is the manifest: the model takes it from there
    for name, default in manifest.items():
        assert PersonalSettingsRead.model_fields[name].default == default, name
    assert manifest == {"mark_resolved_references": False}
    field = FORMS["personal"].sections[0].fields[0]
    assert (field.key, field.widget) == ("mark_resolved_references", "switch")


def test_a_setting_that_was_never_set_has_its_default(client: TestClient) -> None:
    assert client.get(URL).json() == {"mark_resolved_references": False}


def test_a_setting_is_changed_kept_and_published(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    changed = client.put(URL, json={"mark_resolved_references": True})
    assert changed.status_code == 200 and changed.json() == {"mark_resolved_references": True}
    assert client.get(URL).json() == {"mark_resolved_references": True}  # stored
    assert ("settings.changed", {"personal": {"mark_resolved_references": True}}) in published
    assert client.put(URL, json={}).json() == {"mark_resolved_references": True}  # left out: kept
    assert client.put(URL, json={"mark_resolved_references": False}).json() == {
        "mark_resolved_references": False
    }


@pytest.mark.parametrize(
    "body",
    [{"mark_resolved_references": "banana"}, {"mark_resolved_references": 1}, {"other": True}],
)
def test_a_wrong_value_or_an_unknown_setting_is_refused(
    client: TestClient, body: dict[str, Any]
) -> None:
    refused = client.put(URL, json=body)
    assert refused.status_code == 422, refused.text
    assert client.get(URL).json() == {"mark_resolved_references": False}  # nothing was written


# ── what the server sends with an artifact ──────────────────────────


def _artifact(client: TestClient) -> dict[str, Any]:
    fields = [{"name": "secret", "label": "Secret", "kind": "text"}]
    assert client.put("/api/artifact-fields", json={"fields": fields}).status_code == 200
    made = client.post(
        "/api/tasks",
        json={
            "title": "A",
            "body": "The word is ${card.secret}, so be quiet.",
            "fields": {"secret": "bye"},
        },
    )
    assert made.status_code == 201, made.text
    return made.json()  # type: ignore[no-any-return]


def test_without_the_setting_there_are_no_segments(client: TestClient) -> None:
    task = _artifact(client)
    one = client.get(f"/api/tasks/{task['id']}").json()
    assert one["body_resolved"] == "The word is bye, so be quiet."
    assert one["body_resolved_segments"] is None
    listed = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert listed["preview"] and listed["preview_segments"] is None


def test_with_the_setting_the_server_tells_filled_in_text_from_written_text(
    client: TestClient,
) -> None:
    task = _artifact(client)
    client.put(URL, json={"mark_resolved_references": True}).raise_for_status()
    one = client.get(f"/api/tasks/{task['id']}").json()
    assert one["body_resolved_segments"] == [
        {"text": "The word is ", "resolved": False},
        {"text": "bye", "resolved": True},
        {"text": ", so be quiet.", "resolved": False},
    ]
    listed = next(t for t in client.get("/api/tasks").json() if t["id"] == task["id"])
    assert any(s["resolved"] for s in listed["preview_segments"])  # the board's cards too
    # a body without a reference has nothing to mark
    plain = client.post("/api/tasks", json={"title": "B", "body": "Nothing to fill."}).json()
    assert client.get(f"/api/tasks/{plain['id']}").json()["body_resolved_segments"] is None

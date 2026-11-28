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
STORAGE = {
    "storage_keep_executions": None,
    "storage_step_data_days": None,
    "storage_run_data_mib": None,
    "storage_step_output_kib": None,
    "storage_run_output_kib": None,
    "storage_clean_interval_hours": None,
    "storage_warn_mib": None,
}  # the Data storage settings (ADR-084): all empty by default
OFF = {
    "mark_resolved_references": False,
    "show_stop_switch": False,
    "board_view": "classic",
    "board_groups_open": "closed",
    **STORAGE,
}  # every setting at its default


def test_the_models_and_the_manifest_declare_the_same_settings() -> None:
    manifest = personal_settings.defaults()
    assert set(PersonalSettingsRead.model_fields) == set(manifest)
    assert set(PersonalSettingsWrite.model_fields) == set(manifest)
    # the one place that declares a default is the manifest: the model takes it from there
    for name, default in manifest.items():
        assert PersonalSettingsRead.model_fields[name].default == default, name
    assert manifest == {
        "mark_resolved_references": False,
        "show_stop_switch": False,
        "board_view": "classic",
        "board_groups_open": "closed",
        **STORAGE,
    }  # ADR-076 added the second, ADR-095 the board view, ADR-084 the seven of Data storage
    field = FORMS["personal"].sections[0].fields[0]
    assert (field.key, field.widget) == ("mark_resolved_references", "switch")


def test_a_setting_that_was_never_set_has_its_default(client: TestClient) -> None:
    assert client.get(URL).json() == OFF


def test_a_setting_is_changed_kept_and_published(
    client: TestClient, published: list[tuple[str, dict[str, Any]]]
) -> None:
    changed = client.put(URL, json={"mark_resolved_references": True})
    assert changed.status_code == 200 and changed.json() == {
        **OFF,
        "mark_resolved_references": True,
    }
    assert client.get(URL).json() == {**OFF, "mark_resolved_references": True}  # stored
    assert (
        "settings.changed",
        {"personal": {**OFF, "mark_resolved_references": True}},
    ) in published
    assert client.put(URL, json={}).json() == {
        **OFF,
        "mark_resolved_references": True,
    }  # left out: kept
    assert client.put(URL, json={"mark_resolved_references": False}).json() == OFF


@pytest.mark.parametrize(
    "body",
    [{"mark_resolved_references": "banana"}, {"mark_resolved_references": 1}, {"other": True}],
)
def test_a_wrong_value_or_an_unknown_setting_is_refused(
    client: TestClient, body: dict[str, Any]
) -> None:
    refused = client.put(URL, json=body)
    assert refused.status_code == 422, refused.text
    assert client.get(URL).json() == OFF  # nothing was written


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


def test_every_data_storage_setting_is_empty_by_default_so_nothing_changes(
    client: TestClient,
) -> None:
    """ADR-084: a user who never opens the section gets today's behaviour (every limit empty)."""
    body = client.get(URL).json()
    assert {k: v for k, v in body.items() if k.startswith("storage_")} == STORAGE


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("storage_keep_executions", -1),
        ("storage_keep_executions", 100001),
        ("storage_step_data_days", 0),
        ("storage_step_output_kib", 257),
        ("storage_run_output_kib", 1025),
        ("storage_clean_interval_hours", 0),
        ("storage_warn_mib", 0),
    ],
)
def test_a_data_storage_limit_outside_its_bounds_is_refused_in_plain_words(
    client: TestClient, name: str, bad: int
) -> None:
    response = client.put(URL, json={name: bad})
    assert response.status_code == 422
    assert "use a number from" in response.text and "or leave it empty" in response.text
    assert client.get(URL).json()[name] is None  # nothing was stored


def test_a_data_storage_limit_is_stored_and_null_clears_it(client: TestClient) -> None:
    assert (
        client.put(URL, json={"storage_step_output_kib": 64}).json()["storage_step_output_kib"]
        == 64
    )
    assert client.get(URL).json()["storage_step_output_kib"] == 64
    assert (
        client.put(URL, json={"storage_step_output_kib": None}).json()["storage_step_output_kib"]
        is None
    )


def test_the_board_view_is_classic_until_set_and_takes_only_the_two_views(
    client: TestClient,
) -> None:
    assert client.get(URL).json()["board_view"] == "classic"
    assert client.put(URL, json={"board_view": "grouped"}).json()["board_view"] == "grouped"
    assert client.get(URL).json()["board_view"] == "grouped"  # stored
    assert (
        client.put(URL, json={"mark_resolved_references": True}).json()["board_view"] == "grouped"
    )  # left out: kept
    for refused in ("clustered", "", None, 1):
        answer = client.put(URL, json={"board_view": refused})
        assert answer.status_code == 422, refused
    assert client.get(URL).json()["board_view"] == "grouped"  # a refused value changed nothing
    assert client.put(URL, json={"board_view": "classic"}).json()["board_view"] == "classic"


def test_the_accordion_default_is_closed_until_set_and_takes_only_closed_or_open(
    client: TestClient,
) -> None:
    assert client.get(URL).json()["board_groups_open"] == "closed"
    assert client.put(URL, json={"board_groups_open": "open"}).json()["board_groups_open"] == "open"
    assert client.get(URL).json()["board_groups_open"] == "open"  # stored
    left_out = client.put(URL, json={"board_view": "grouped"}).json()
    assert left_out["board_groups_open"] == "open"  # left out: kept
    for refused in ("expanded", "", None, 1, True):
        assert client.put(URL, json={"board_groups_open": refused}).status_code == 422, refused
    assert client.get(URL).json()["board_groups_open"] == "open"  # a refused value changed nothing


def test_the_accordion_setting_is_greyed_unless_the_board_view_is_grouped() -> None:
    fields = {f.key: f for section in FORMS["personal"].sections for f in section.fields}
    field = fields["board_groups_open"]
    assert field.enabled_when is not None
    assert (field.enabled_when.field, field.enabled_when.equals) == ("board_view", "grouped")
    assert field.disabled_help  # the reason is declared; the window shows it under the field

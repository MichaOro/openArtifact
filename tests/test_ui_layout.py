"""The layout layer of the manifest windows (ADR-063): a saved arrangement of the sections and fields of a window is merged over
the shipped manifest, never written into it; stale keys are ignored and new keys appear at their default place; what is
saved is validated; the API stores, resets and exports it."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from openartifact.graph.node_types import NODE_TYPES
from openartifact.ui import forms, layout
from openartifact.ui.layout import LayoutError


def guard() -> dict[str, Any]:
    return forms.describe(forms.FORMS["guard"])


def keys(description: dict[str, Any]) -> list[str]:
    return [s["key"] for s in description["sections"]]


def fields(description: dict[str, Any], section: str) -> list[tuple[str, bool]]:
    found = next(s for s in description["sections"] if s["key"] == section)
    return [(f["key"], bool(f.get("advanced"))) for f in found["fields"]]


# ── forms ─────────────────────────────────────────────────────────────


def test_the_shipped_layout_changes_nothing() -> None:
    shipped = guard()
    merged = layout.apply_form_layout(shipped, layout.shipped_form_layout(shipped))
    assert keys(merged) == keys(shipped)
    assert [fields(merged, k) for k in keys(merged)] == [fields(shipped, k) for k in keys(shipped)]


def test_sections_and_fields_follow_a_saved_arrangement() -> None:
    shipped = guard()
    saved = layout.shipped_form_layout(shipped)
    sections = {s["key"]: s for s in saved["sections"]}
    sections["then"]["column"] = 1
    sections["trigger"]["column"] = 2
    sections["trigger"]["fields"] = ["trigger.events", "trigger.type", "trigger.every_seconds"]
    saved["sections"] = [
        sections[k] for k in ("then", "condition", "trigger", "escalation", "logic")
    ]
    merged = layout.apply_form_layout(shipped, saved)
    assert keys(merged)[:3] == ["then", "condition", "trigger"]
    assert next(s for s in merged["sections"] if s["key"] == "then")["column"] == 1
    assert [k for k, _ in fields(merged, "trigger")][:3] == [
        "trigger.events",
        "trigger.type",
        "trigger.every_seconds",
    ]
    assert merged["layout_customised"] is True


def test_a_field_moves_into_and_out_of_the_folded_group() -> None:
    shipped = guard()
    saved = layout.shipped_form_layout(shipped)
    trigger = next(s for s in saved["sections"] if s["key"] == "trigger")
    trigger["fields"].remove("trigger.every_seconds")
    trigger["advanced"].insert(0, "trigger.every_seconds")
    trigger["advanced"].remove("trigger.for_seconds")
    trigger["fields"].append("trigger.for_seconds")
    merged = layout.apply_form_layout(shipped, saved)
    flags = dict(fields(merged, "trigger"))
    assert flags["trigger.every_seconds"] is True
    assert flags["trigger.for_seconds"] is False


def test_a_required_field_is_never_folded_away() -> None:
    shipped = guard()
    saved = layout.shipped_form_layout(shipped)
    trigger = next(s for s in saved["sections"] if s["key"] == "trigger")
    trigger["fields"].remove("trigger.events")  # required in the manifest
    trigger["advanced"].append("trigger.events")
    merged = layout.apply_form_layout(shipped, saved)
    assert dict(fields(merged, "trigger"))["trigger.events"] is False


def test_stale_keys_are_ignored_and_new_keys_keep_their_default_place() -> None:
    shipped = guard()
    saved = {
        "sections": [
            {"key": "gone", "column": 1, "fields": ["x"], "advanced": []},
            {
                "key": "then",
                "column": 2,
                "fields": ["consequence", "no_such_field"],
                "advanced": [],
            },
            {"key": "trigger", "column": 1, "fields": ["trigger.type"], "advanced": []},
        ]
    }
    merged = layout.apply_form_layout(shipped, saved)
    assert sorted(keys(merged)) == sorted(keys(shipped))  # nothing lost, nothing invented
    assert keys(merged).index("then") < keys(merged).index("trigger")
    assert "no_such_field" not in [k for k, _ in fields(merged, "then")]
    # fields the saved layout does not know sit where the manifest has them, after the field before them
    trigger = [k for k, _ in fields(merged, "trigger")]
    assert trigger[0] == "trigger.type" and set(trigger) == {
        k for k, _ in fields(shipped, "trigger")
    }
    assert trigger.index("trigger.events") == 1


def test_a_full_width_section_stays_full_width() -> None:
    shipped = guard()
    saved = layout.shipped_form_layout(shipped)
    next(s for s in saved["sections"] if s["key"] == "condition")["column"] = 1
    merged = layout.apply_form_layout(shipped, saved)
    assert next(s for s in merged["sections"] if s["key"] == "condition")["column"] == "full"


def test_a_layout_is_checked_before_it_is_saved() -> None:
    shipped = guard()

    def refused(change: Any, match: str) -> None:
        saved = copy.deepcopy(layout.shipped_form_layout(shipped))
        change(saved)
        with pytest.raises(LayoutError, match=match):
            layout.check_form_layout(shipped, saved)

    refused(
        lambda s: s["sections"].append({"key": "extra", "column": 1, "fields": [], "advanced": []}),
        "unknown section",
    )
    refused(lambda s: s["sections"].append(copy.deepcopy(s["sections"][0])), "more than once")
    refused(lambda s: s["sections"][0].update(column=3), "column")
    refused(
        lambda s: next(x for x in s["sections"] if x["key"] == "condition").update(column=1),
        "full width",
    )
    refused(lambda s: s["sections"][0]["fields"].append("consequence"), "not a field of section")
    refused(
        lambda s: s["sections"][0]["fields"].append(s["sections"][0]["fields"][0]), "more than once"
    )
    refused(
        lambda s: (
            s["sections"][0]["fields"].remove("trigger.events"),
            s["sections"][0]["advanced"].append("trigger.events"),
        ),
        "required",
    )
    refused(lambda s: s["sections"][0].update(surprise=1), "unknown key")
    with pytest.raises(LayoutError, match="sections"):
        layout.check_form_layout(shipped, {"nothing": []})


# ── nodes ─────────────────────────────────────────────────────────────


def node(kind: str = "agent") -> dict[str, Any]:
    return NODE_TYPES[kind].describe()


def order(description: dict[str, Any], section: str) -> list[str]:
    return [
        s["key"] for s in description["settings"] if (s.get("section") or "definition") == section
    ]


def test_a_node_layout_reorders_settings_and_swaps_the_sides() -> None:
    shipped = node("http")
    saved = layout.shipped_node_layout(shipped)
    definition = next(s for s in saved["sections"] if s["key"] == "definition")
    definition["fields"] = list(reversed(definition["fields"]))
    saved["sections"].reverse()
    merged = layout.apply_node_layout(shipped, saved)
    assert order(merged, "definition") == list(reversed(order(shipped, "definition")))
    assert merged["layout"] == {"sections": ["behaviour", "definition"]}
    assert merged["layout_customised"] is True
    assert sorted(s["key"] for s in merged["settings"]) == sorted(
        s["key"] for s in shipped["settings"]
    )


def test_a_group_of_settings_moves_as_one_entry() -> None:
    shipped = node("if")
    saved = layout.shipped_node_layout(shipped)
    definition = next(s for s in saved["sections"] if s["key"] == "definition")
    assert "group:Condition 1" in definition["fields"] and "left_1" not in definition["fields"]
    definition["fields"].remove("group:Condition 1")
    definition["fields"].append("group:Condition 1")
    merged = layout.apply_node_layout(shipped, saved)
    keys_in_order = order(merged, "definition")
    assert keys_in_order[-3:] == ["left_1", "operator_1", "right_1"]


def test_a_node_layout_ignores_stale_entries_and_checks_what_is_saved() -> None:
    shipped = node("code")
    merged = layout.apply_node_layout(
        shipped, {"sections": [{"key": "definition", "fields": ["language", "nope"]}]}
    )
    assert order(merged, "definition") == order(shipped, "definition")
    with pytest.raises(LayoutError, match="not in section"):
        layout.check_node_layout(
            shipped, {"sections": [{"key": "definition", "fields": ["on_failure"]}]}
        )
    with pytest.raises(LayoutError, match="unknown section"):
        layout.check_node_layout(shipped, {"sections": [{"key": "elsewhere", "fields": []}]})
    with pytest.raises(LayoutError, match="column"):
        layout.check_node_layout(
            shipped, {"sections": [{"key": "definition", "fields": [], "column": 2}]}
        )


# ── the API ───────────────────────────────────────────────────────────

GUARD = "/api/ui-layouts/forms/guard"


def shipped_of(client: TestClient, window: str = GUARD) -> dict[str, Any]:
    return client.get(window).json()["shipped"]


def test_a_layout_is_saved_merged_into_the_description_and_reset(client: TestClient) -> None:
    before = client.get(GUARD).json()
    assert before["customised"] is False and before["layout"] == before["shipped"]
    saved = copy.deepcopy(before["shipped"])
    saved["sections"].reverse()
    put = client.put(GUARD, json=saved)
    assert put.status_code == 200, put.text
    assert put.json()["customised"] is True
    form = client.get("/api/forms/guard").json()
    assert form["layout_customised"] is True
    assert [s["key"] for s in form["sections"]] == [s["key"] for s in saved["sections"]]
    reset = client.delete(GUARD)
    assert reset.status_code == 200 and reset.json()["customised"] is False
    assert "layout_customised" not in client.get("/api/forms/guard").json()
    assert [s["key"] for s in client.get("/api/forms/guard").json()["sections"]] == keys(guard())


def test_a_node_layout_reaches_the_node_types(client: TestClient) -> None:
    window = "/api/ui-layouts/nodes/http"
    shipped = shipped_of(client, window)
    saved = copy.deepcopy(shipped)
    saved["sections"].reverse()
    assert client.put(window, json=saved).status_code == 200
    kind = next(k for k in client.get("/api/node-types").json() if k["kind"] == "http")
    assert (
        kind["layout"] == {"sections": ["behaviour", "definition"]}
        and kind["layout_customised"] is True
    )
    other = next(k for k in client.get("/api/node-types").json() if k["kind"] == "code")
    assert "layout" not in other
    client.delete(window)
    assert "layout" not in next(
        k for k in client.get("/api/node-types").json() if k["kind"] == "http"
    )


def test_an_invalid_layout_is_refused_and_nothing_is_stored(client: TestClient) -> None:
    saved = copy.deepcopy(shipped_of(client))
    saved["sections"][0]["fields"].append("consequence")
    bad = client.put(GUARD, json=saved)
    assert bad.status_code == 422 and "not a field of section" in bad.json()["detail"]
    assert client.get(GUARD).json()["customised"] is False
    assert client.get("/api/ui-layouts/forms/nope").status_code == 404
    assert client.get("/api/ui-layouts/things/guard").status_code == 404
    assert client.put(GUARD, json={"sections": "x"}).status_code == 422


def test_the_export_is_the_merged_layout_as_yaml(client: TestClient) -> None:
    saved = copy.deepcopy(shipped_of(client))
    saved["sections"].reverse()
    client.put(GUARD, json=saved)
    response = client.get(f"{GUARD}/export")
    assert response.status_code == 200
    assert "guard.layout.yaml" in response.headers["content-disposition"]
    exported = yaml.safe_load(response.text)
    assert exported["window"] == "forms/guard"
    assert [s["key"] for s in exported["layout"]["sections"]] == [
        s["key"] for s in saved["sections"]
    ]
    client.delete(GUARD)


def test_a_stale_stored_layout_does_not_break_the_window(client: TestClient) -> None:
    stale = {"sections": [{"key": "retired", "column": 1, "fields": ["x"], "advanced": []}]}
    from openartifact.database import (
        new_session,
    )  # the stored document is plain data: write what an older manifest left

    async def store() -> None:
        async with new_session() as session:
            await layout.save_raw(session, "forms/guard", stale)
            await session.commit()

    client.portal.call(store)  # type: ignore[attr-defined]
    form = client.get("/api/forms/guard")
    assert form.status_code == 200
    assert [s["key"] for s in form.json()["sections"]] == keys(guard())
    client.delete(GUARD)


def test_the_integration_api_has_the_same_routes_and_needs_the_token(client: TestClient) -> None:
    assert client.get("/api/v1/ui-layouts/forms/guard").status_code == 401

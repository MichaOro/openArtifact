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
    refused(lambda s: s["sections"][0]["fields"].append("nope"), "not a field of this form")
    refused(
        lambda s: s["sections"][0]["fields"].append("consequence"), "more than once"
    )  # it sits in another section too
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
    with pytest.raises(LayoutError, match="not a setting of this kind"):
        layout.check_node_layout(
            shipped, {"sections": [{"key": "definition", "fields": ["no_such_setting"]}]}
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
    saved["sections"][0]["fields"].append("nope")
    bad = client.put(GUARD, json=saved)
    assert bad.status_code == 422 and "not a field of this form" in bad.json()["detail"]
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


# ── areas: a setting in any area, and areas of one's own (ADR-063 addendum) ─────────────


def area_of(description: dict[str, Any], key: str) -> str:
    return next(s["section"] for s in description["settings"] if s["key"] == key)


def test_a_setting_sits_in_any_area_of_a_node_and_keeps_its_meaning() -> None:
    shipped = node("agent")
    saved = copy.deepcopy(layout.shipped_node_layout(shipped))
    definition, behaviour = saved["sections"]
    definition["fields"].remove("user_prompt")
    behaviour["fields"].insert(0, "user_prompt")
    behaviour["fields"].remove("on_failure")
    definition["fields"].append("on_failure")
    merged = layout.apply_node_layout(shipped, layout.check_node_layout(shipped, saved))
    assert area_of(merged, "user_prompt") == "behaviour"
    assert area_of(merged, "on_failure") == "definition"
    levels = {s["key"]: (s.get("level"), s.get("inherits")) for s in shipped["settings"]}
    assert {s["key"]: (s.get("level"), s.get("inherits")) for s in merged["settings"]} == levels
    assert (
        next(s["key"] for s in merged["settings"] if s["section"] == "behaviour") == "user_prompt"
    )


def test_the_block_a_kind_draws_itself_is_fixed() -> None:
    shipped = node("agent")
    with pytest.raises(LayoutError, match="stays where it is"):
        layout.check_node_layout(
            shipped, {"sections": [{"key": "behaviour", "fields": ["agent_id"]}]}
        )
    merged = layout.apply_node_layout(shipped, {"sections": [{"key": "behaviour", "fields": []}]})
    first = [s["key"] for s in merged["settings"]][:2]
    assert first == ["agent_id", "inputs"] and area_of(merged, "agent_id") == "definition"
    assert "agent_id" not in layout.current_node_layout(merged)["sections"][0]["fields"]


def test_an_area_of_ones_own_is_a_container_with_a_title_and_may_stay_empty() -> None:
    shipped = node("code")
    saved = copy.deepcopy(layout.shipped_node_layout(shipped))
    saved["sections"].append({"key": "custom_empty", "title": "  Later  ", "fields": []})
    saved["sections"].append({"key": "custom_a1", "title": "Mine", "fields": ["on_failure"]})
    saved["sections"][1]["fields"].remove("on_failure")
    merged = layout.apply_node_layout(shipped, layout.check_node_layout(shipped, saved))
    assert merged["layout"]["sections"] == ["definition", "behaviour", "custom_empty", "custom_a1"]
    assert merged["layout"]["titles"] == {"custom_empty": "Later", "custom_a1": "Mine"}
    assert area_of(merged, "on_failure") == "custom_a1"
    current = layout.current_node_layout(merged)
    assert [(s["key"], s.get("title")) for s in current["sections"]][2:] == [
        ("custom_empty", "Later"),
        ("custom_a1", "Mine"),
    ]
    assert current["sections"][2]["fields"] == []  # an empty area is kept for the arrange view
    # dropped from the document it is gone, and what it held is back where it ships
    saved["sections"] = [s for s in saved["sections"] if not s["key"].startswith("custom_")]
    saved["sections"][1]["fields"].append("on_failure")
    back = layout.apply_node_layout(shipped, saved)
    assert "titles" not in back["layout"] and area_of(back, "on_failure") == "behaviour"


def test_the_rules_of_an_area_of_ones_own_are_checked() -> None:
    shipped = node("code")

    def refused(section: dict[str, Any], match: str, *more: dict[str, Any]) -> None:
        with pytest.raises(LayoutError, match=match):
            layout.check_node_layout(shipped, {"sections": [section, *more]})

    refused({"key": "custom_a", "fields": []}, "title")
    refused({"key": "custom_a", "title": "", "fields": []}, "title")
    refused({"key": "custom_a", "title": "x" * 41, "fields": []}, "1 to 40")
    refused({"key": "definition", "title": "Mine", "fields": []}, "cannot be renamed")
    refused({"key": "Custom A", "title": "Mine", "fields": []}, "unknown section")
    refused({"key": "area", "title": "Mine", "fields": []}, "unknown section")
    refused(
        {"key": "custom_a", "title": "A", "fields": []},
        "more than once",
        {"key": "custom_a", "title": "B", "fields": []},
    )
    refused({"key": "custom_a", "title": "A", "fields": ["language", "language"]}, "more than once")
    refused(
        {"key": "custom_a", "title": "A", "fields": ["language"]},
        "more than once",
        {"key": "definition", "fields": ["language"]},
    )
    twelve = [{"key": f"custom_{i}", "title": f"A{i}", "fields": []} for i in range(13)]
    with pytest.raises(LayoutError, match="at most 12"):
        layout.check_node_layout(shipped, {"sections": twelve})
    layout.check_node_layout(shipped, {"sections": twelve[:12]})


def test_a_node_layout_saved_before_areas_existed_is_read_and_stale_areas_are_ignored() -> None:
    shipped = node("http")
    old = {
        "sections": [
            {"key": "behaviour", "fields": ["on_failure"]},
            {"key": "definition", "fields": ["url"]},
            {"key": "custom_gone!", "title": "x", "fields": ["method"]},  # not a valid key: ignored
            {"key": "retired", "fields": ["headers"]},
        ]
    }
    merged = layout.apply_node_layout(shipped, old)
    assert merged["layout"]["sections"] == ["behaviour", "definition"]
    assert (
        area_of(merged, "method") == "definition"
    )  # its shipped place: the ignored area kept nothing
    assert sorted(s["key"] for s in merged["settings"]) == sorted(
        s["key"] for s in shipped["settings"]
    )


def test_a_field_moves_to_another_section_and_a_custom_section_holds_it() -> None:
    shipped = guard()
    saved = copy.deepcopy(layout.shipped_form_layout(shipped))
    by = {s["key"]: s for s in saved["sections"]}
    by["then"]["fields"].remove("consequence")
    saved["sections"].append(
        {
            "key": "custom_x1",
            "title": "My area",
            "column": 2,
            "fields": ["consequence"],
            "advanced": [],
        }
    )
    saved["sections"].append(
        {"key": "custom_empty", "title": "Later", "column": "auto", "fields": [], "advanced": []}
    )
    merged = layout.apply_form_layout(shipped, layout.check_form_layout(shipped, saved))
    mine = next(s for s in merged["sections"] if s["key"] == "custom_x1")
    assert mine["title"] == "My area" and mine["column"] == 2
    assert [f["key"] for f in mine["fields"]] == ["consequence"]
    assert "consequence" not in [k for k, _ in fields(merged, "then")]
    assert "custom_empty" not in keys(merged)  # an empty section is not drawn
    areas = merged["layout"]["areas"]
    assert [a["key"] for a in areas][-2:] == ["custom_x1", "custom_empty"]
    assert [a["custom"] for a in areas][-2:] == [True, True]
    current = layout.current_form_layout(merged)
    assert current["sections"][-2]["title"] == "My area"
    assert current["sections"][-1] == {
        "key": "custom_empty",
        "column": "auto",
        "fields": [],
        "advanced": [],
        "title": "Later",
    }


def test_the_rules_of_a_custom_section_of_a_form_are_checked() -> None:
    shipped = guard()

    def refused(change: Any, match: str) -> None:
        saved = copy.deepcopy(layout.shipped_form_layout(shipped))
        change(saved)
        with pytest.raises(LayoutError, match=match):
            layout.check_form_layout(shipped, saved)

    refused(lambda s: s["sections"].append({"key": "custom_a", "fields": []}), "title")
    refused(
        lambda s: s["sections"].append(
            {"key": "custom_a", "title": "A", "column": "full", "fields": []}
        ),
        "cannot become full width",
    )
    refused(lambda s: s["sections"][0].update(title="Renamed"), "cannot be renamed")
    refused(
        lambda s: s["sections"].extend(
            {"key": f"custom_{i}", "title": f"A{i}", "fields": []} for i in range(13)
        ),
        "at most 12",
    )


# ── the API with areas ────────────────────────────────────────────────


def test_areas_of_ones_own_are_saved_served_exported_and_reset(client: TestClient) -> None:
    window = "/api/ui-layouts/nodes/code"
    shipped = shipped_of(client, window)
    saved = copy.deepcopy(shipped)
    saved["sections"][1]["fields"].remove("on_failure")
    saved["sections"].append({"key": "custom_q1", "title": "Quick", "fields": ["on_failure"]})
    put = client.put(window, json=saved)
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["customised"] is True
    custom = next(s for s in body["layout"]["sections"] if s["key"] == "custom_q1")
    assert custom == {"key": "custom_q1", "title": "Quick", "fields": ["on_failure"]}
    kind = next(k for k in client.get("/api/node-types").json() if k["kind"] == "code")
    assert kind["layout"]["titles"] == {"custom_q1": "Quick"}
    assert next(s["section"] for s in kind["settings"] if s["key"] == "on_failure") == "custom_q1"
    # the export is the layout as YAML and it loads back into the same layout
    exported = yaml.safe_load(client.get(f"{window}/export").text)
    code = NODE_TYPES["code"].describe()
    assert layout.check_node_layout(code, exported["layout"]) == body["layout"]
    assert client.delete(window).json()["customised"] is False
    after = next(k for k in client.get("/api/node-types").json() if k["kind"] == "code")
    assert "layout" not in after


def test_a_form_with_a_custom_section_is_served_and_its_export_loads_back(
    client: TestClient,
) -> None:
    saved = copy.deepcopy(shipped_of(client))
    next(s for s in saved["sections"] if s["key"] == "then")["fields"].remove("consequence")
    saved["sections"].append(
        {
            "key": "custom_f1",
            "title": "Mine",
            "column": 1,
            "fields": ["consequence"],
            "advanced": [],
        }
    )
    saved["sections"].append(
        {"key": "custom_f2", "title": "Spare", "column": "auto", "fields": [], "advanced": []}
    )
    put = client.put(GUARD, json=saved)
    assert put.status_code == 200, put.text
    form = client.get("/api/forms/guard").json()
    assert "custom_f1" in [s["key"] for s in form["sections"]]
    assert "custom_f2" not in [s["key"] for s in form["sections"]]
    assert [a["key"] for a in form["layout"]["areas"]][-2:] == ["custom_f1", "custom_f2"]
    exported = yaml.safe_load(client.get(f"{GUARD}/export").text)
    assert layout.check_form_layout(guard(), exported["layout"]) == put.json()["layout"]
    bad = copy.deepcopy(saved)
    bad["sections"].append({"key": "custom_f3", "title": "", "fields": []})
    refused = client.put(GUARD, json=bad)
    assert refused.status_code == 422 and "title" in refused.json()["detail"]
    client.delete(GUARD)

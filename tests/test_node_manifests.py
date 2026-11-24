"""The node kinds as YAML manifests (ADR-054): they are valid, what they declare is what the application uses, a bad one is
refused with its file name, and the description the editor gets is kept in a fixture the JS tests read."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from openartifact.graph import manifest
from openartifact.graph.manifest import CLIENT_FUNCTIONS, ManifestError, NodeManifest
from openartifact.graph.node_types import (
    IF_ROWS,
    NODE_TYPES,
    OPERATORS,
    SWITCH_CASES,
    TIMER_MAX_SECONDS,
    TIMER_MIN_SECONDS,
    node_type,
)
from openartifact.models import NodeKind

FIXTURE = Path(__file__).parent / "fixtures" / "node-types.json"
PLACEHOLDER_FIXTURE = Path(__file__).parent / "fixtures" / "menu-placeholders.json"


def _write(directory: Path, name: str, data: dict[str, Any]) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _minimal(**more: Any) -> dict[str, Any]:
    return {"schema": 1, "kind": "timer", "label": "Timer", **more}


def test_every_shipped_manifest_is_valid_and_every_kind_has_one() -> None:
    manifests = manifest.read_all()
    assert {m.kind for m in manifests} == {k.value for k in NodeKind}
    assert [m.kind for m in manifests] == [
        k.value for k in NODE_TYPES
    ]  # the order _menu.yaml gives


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_minimal(behaviour="teleport"), "behaviour"),
        (_minimal(schema=2), "schema 2 is not known"),
        (_minimal(colour="red"), "colour"),
        (
            _minimal(
                settings=[{"key": "x", "label": "X", "type": "text", "check": "no_such_rule"}]
            ),
            "unknown rule",
        ),
        (
            _minimal(settings=[{"key": "x", "label": "X", "type": "text", "section": "middle"}]),
            "section",
        ),
        (_minimal(settings=[{"label": "X"}]), "needs key, label and type"),
        (_minimal(ui={"caption": {"fn": "no_such_fn"}}), "unknown caption function"),
        (_minimal(ui={"caption": {"template": "{x|shout}"}}), "unknown filter"),
        (_minimal(ui={"caption": {"template": "a", "fn": "if_summary"}}), "either template or fn"),
        (
            _minimal(
                ports={"outputs": [{"name": "o", "label": "O", "visible_when": {"fn": "nope"}}]}
            ),
            "unknown function",
        ),
        (_minimal(ports={"outputs": [{"name": "o", "label": "O", "repeat": 3}]}), "{n}"),
    ],
)
def test_a_manifest_that_says_something_unknown_is_refused_with_its_file_name(
    tmp_path: Path, data: dict[str, Any], message: str
) -> None:
    path = _write(tmp_path, "broken", data)
    with pytest.raises(ManifestError, match=r"broken\.yaml") as error:
        manifest.read(path)
    assert message in str(error.value)


def test_a_file_that_is_not_yaml_is_refused_with_its_name(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("kind: [unclosed", encoding="utf-8")
    with pytest.raises(ManifestError, match=r"bad\.yaml: not valid YAML"):
        manifest.read(path)


def test_a_repeated_block_is_written_out_with_the_number_and_what_only_the_first_has() -> None:
    spec = NodeManifest.model_validate(
        _minimal(
            settings=[
                {
                    "repeat": 3,
                    "settings": [
                        {
                            "key": "v_{n}",
                            "label": "Value",
                            "type": "text",
                            "group": "Row {n}",
                            "first": {"help": "Said once"},
                        },
                        {
                            "key": "o_{n}",
                            "label": "Op",
                            "type": "select",
                            "options": ["a"],
                            "group": "Row {n}",
                        },
                    ],
                }
            ]
        )
    )
    expanded = manifest.expand_settings(spec.settings, {})
    assert [s["key"] for s in expanded] == ["v_1", "o_1", "v_2", "o_2", "v_3", "o_3"]
    assert [s.get("group") for s in expanded[:3]] == ["Row 1", "Row 1", "Row 2"]
    assert [s.get("help") for s in expanded if s["key"].startswith("v_")] == [
        "Said once",
        None,
        None,
    ]


def test_a_shared_setting_is_filled_in_and_what_is_given_beside_it_wins() -> None:
    shared = {
        "op": {
            "key": "op",
            "label": "Operator",
            "type": "select",
            "options": ["a", "b"],
            "default": "a",
        }
    }
    spec = NodeManifest.model_validate(
        _minimal(settings=[{"use": "op", "key": "op_2", "label": "Second"}])
    )
    (only,) = manifest.expand_settings(spec.settings, shared)
    assert (only["key"], only["label"], only["options"], only["default"]) == (
        "op_2",
        "Second",
        ["a", "b"],
        "a",
    )
    unknown = NodeManifest.model_validate(_minimal(settings=[{"use": "missing"}]))
    with pytest.raises(ValueError, match="no shared setting named 'missing'"):
        manifest.expand_settings(unknown.settings, shared)


def test_a_repeated_port_is_written_out() -> None:
    ports = manifest.expand_ports([manifest.PortSpec(name="case_{n}", label="Case {n}", repeat=2)])
    assert [(p.name, p.label) for p in ports] == [("case_1", "Case 1"), ("case_2", "Case 2")]


def test_what_the_python_side_knows_equals_what_the_manifests_declare() -> None:
    timer = {s.key: s for s in node_type(NodeKind.TIMER).settings}["seconds"]
    assert (timer.minimum, timer.maximum) == (TIMER_MIN_SECONDS, TIMER_MAX_SECONDS)
    iff = node_type(NodeKind.IF).settings
    assert len([s for s in iff if s.key.startswith("left_")]) == IF_ROWS
    assert all(s.options == OPERATORS for s in iff if s.key.startswith("operator_"))
    switch = node_type(NodeKind.SWITCH)
    assert len([s for s in switch.settings if s.key.startswith("case_operator_")]) == SWITCH_CASES
    assert len([p for p in switch.outputs if p.name.startswith("case_")]) == SWITCH_CASES
    assert all(
        s.options == OPERATORS for s in switch.settings if s.key.startswith("case_operator_")
    )


def test_every_function_a_manifest_names_exists_in_the_list_the_editor_is_checked_against() -> None:
    named: dict[str, set[str]] = {
        "caption": set(),
        "visible": set(),
        "label": set(),
        "size": set(),
        "group_used": set(),
    }
    for m in manifest.read_all():
        if m.ui.caption and m.ui.caption.fn:
            named["caption"].add(m.ui.caption.fn)
        if m.ui.size_fn:
            named["size"].add(m.ui.size_fn)
        if m.ui.group_used_fn:
            named["group_used"].add(m.ui.group_used_fn)
        for port in [*m.ports.inputs, *m.ports.outputs]:
            if port.visible_when and port.visible_when.fn:
                named["visible"].add(port.visible_when.fn)
            if port.label_from:
                named["label"].add(port.label_from)
    for group, names in named.items():
        assert names <= set(CLIENT_FUNCTIONS[group]), (group, names)
    assert any(named.values())  # the Switch and the summaries do use them


def test_the_json_schema_of_a_manifest_can_be_exported() -> None:
    schema = manifest.schema()
    assert schema["title"] == "NodeManifest"
    assert {"schema", "kind", "label"} <= set(schema["required"])
    assert "behaviour" in schema["properties"]


def test_the_menu_clusters_and_the_kind_order_come_from_the_menu_file() -> None:
    assert manifest.menu_groups()[:2] == ["Structure", "AI"]
    flow = [t for t in NODE_TYPES.values() if t.menu and t.menu["group"] == "Flow"]
    assert sorted((t.menu or {})["order"] for t in flow) == [1, 2, 3]
    assert all(
        t.menu is None for t in NODE_TYPES.values() if not t.addable
    )  # what cannot be added has no place in the menu


def test_the_description_fixture_of_the_editor_tests_is_the_live_answer(client: TestClient) -> None:
    live = client.get("/api/node-types").json()
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(json.dumps(live, indent=1, ensure_ascii=False), encoding="utf-8")
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == live, (
        "run with UPDATE_FIXTURES=1 to write it again"
    )


# ── placeholders of the "+" menu: entries that are no kinds (a place held for something coming) ──────────────


def _menu_dir(tmp_path: Path, placeholders: Any, kinds: tuple[str, ...] = ()) -> Path:
    (tmp_path / "_menu.yaml").write_text(
        yaml.safe_dump(
            {"groups": ["Structure", "Flow"], "kinds": [], "placeholders": placeholders}
        ),
        encoding="utf-8",
    )
    for kind in kinds:
        _write(tmp_path, kind, _minimal(kind=kind))
    return tmp_path


def _entry(**more: Any) -> dict[str, Any]:
    return {
        "key": "guard",
        "label": "Guard",
        "icon": "shield",
        "group": "Structure",
        "order": 3,
        "scopes": ["pipeline"],
        **more,
    }


def test_the_menu_file_holds_a_place_for_guards_and_no_kind_is_behind_it() -> None:
    # Guards exist (ADR-060): the entry is no longer "soon" and both editors offer it: in a pipeline it watches the
    # pipeline, in an action definition the whole action (the nodes have it in their own menu)
    [guard] = manifest.read_placeholders()
    assert (guard.key, guard.label, guard.icon, guard.group, guard.soon) == (
        "guard",
        "Guard",
        "shield",
        "Structure",
        False,
    )
    assert sorted(guard.scopes) == ["action", "pipeline"]
    assert guard.key not in {k.value for k in NodeKind}, "a guard is not a kind of node"
    orders = {
        t.menu["order"]: t.kind
        for t in NODE_TYPES.values()
        if t.menu and t.menu["group"] == "Structure"
    }
    assert orders[1] == "stage" and orders[2] == "pipeline" and guard.order == 3, (
        "right after Pipeline"
    )


def test_a_valid_placeholder_is_read(tmp_path: Path) -> None:
    [spec] = manifest.read_placeholders(_menu_dir(tmp_path, [_entry(soon=False)]))
    assert (spec.key, spec.soon, spec.scopes) == ("guard", False, ["pipeline"])
    (tmp_path / "none").mkdir()
    assert manifest.read_placeholders(_menu_dir(tmp_path / "none", None)) == []


@pytest.mark.parametrize(
    ("entries", "kinds", "message"),
    [
        ([_entry(group="Elsewhere")], (), "unknown cluster 'Elsewhere'"),
        ([_entry(key="timer")], ("timer",), "is a kind or is declared twice"),
        ([_entry(), _entry(label="Again")], (), "is a kind or is declared twice"),
        ([_entry(key="Bad Key")], (), "key"),
        ([_entry(scopes=[])], (), "scopes"),
        ([_entry(scopes=["stage"])], (), "scopes"),
        ([_entry(colour="red")], (), "colour"),
        ([_entry(icon="")], (), "icon"),
    ],
)
def test_a_bad_placeholder_is_refused_with_the_name_of_the_menu_file(
    tmp_path: Path, entries: list[dict[str, Any]], kinds: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ManifestError, match=r"_menu\.yaml: placeholder") as error:
        manifest.read_placeholders(_menu_dir(tmp_path, entries, kinds))
    assert message in str(error.value)


def test_placeholders_are_named_in_the_users_language(monkeypatch: pytest.MonkeyPatch) -> None:
    from openartifact.graph import localize

    assert [p["label"] for p in localize.placeholders("en")] == ["Guard"]
    texts = {"nodes.placeholders.guard.label": "Wächter", "nodes.menu.Structure": "Aufbau"}
    monkeypatch.setattr(localize, "_own", lambda language, key: texts.get(key))
    [guard] = localize.placeholders("de")
    assert (guard["label"], guard["group"]) == ("Wächter", "Aufbau")
    assert guard["group_index"] == 0 and guard["icon"] == "shield" and guard["soon"] is False


def test_the_editor_page_carries_the_placeholders_and_the_fixture_of_the_js_tests_is_that_answer(
    client: TestClient,
) -> None:
    import html
    import re

    page = client.get("/pipelines/anything").text
    carried = re.search(r"data-menu-placeholders='([^']*)'", page)
    assert carried, "the page hands the placeholders to the editor"
    live = json.loads(html.unescape(carried[1]))
    assert [p["key"] for p in live] == ["guard"]
    action_page = client.get("/actions/anything").text
    assert "data-menu-placeholders=" in action_page
    if os.environ.get("UPDATE_FIXTURES"):
        PLACEHOLDER_FIXTURE.write_text(
            json.dumps(live, indent=1, ensure_ascii=False), encoding="utf-8"
        )
    assert json.loads(PLACEHOLDER_FIXTURE.read_text(encoding="utf-8")) == live, (
        "run with UPDATE_FIXTURES=1 to write it again"
    )


def _icon_names() -> set[str]:
    """The names the icon macro knows (``icon_names`` in templates/components/icons.html)."""
    source = (
        Path(manifest.__file__).resolve().parents[1] / "templates" / "components" / "icons.html"
    )
    line = next(
        row for row in source.read_text().splitlines() if "icon_names" in row and "[" in row
    )
    return set(re.findall(r'"([a-z0-9-]+)"', line.split("=", 1)[1]))


def test_every_kind_has_one_glyph_for_the_menus_and_the_glyph_exists() -> None:
    """The "+" menus show a glyph before every kind: the manifest's ``menu_icon`` or else its card icon."""
    known = _icon_names()
    for kind, node in NODE_TYPES.items():
        glyph = node.describe()["menu_icon"]
        assert glyph, f"{kind.value} has no glyph for the menus (menu_icon or ui.icon)"
        assert glyph in known, f"{kind.value}: {glyph!r} is not an icon of icons.html"


def test_a_menu_icon_must_be_a_plain_icon_name(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "schema: 1\nkind: code\nlabel: Bad\nmenu_icon: 'Not An Icon'\n"
    )
    with pytest.raises(manifest.ManifestError, match=r"bad\.yaml"):
        manifest.read(tmp_path / "bad.yaml")

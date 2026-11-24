"""Configuration windows as data (ADR-062): the shipped form manifests are valid and only name widgets the browser has,
a bad one is refused with its file name, and what the browser gets is in its language where a translation exists."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from openartifact.ui import forms
from openartifact.ui.forms import FormError

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "openartifact" / "static" / "js"


def _write(directory: Path, name: str, data: dict[str, Any]) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _form(**more: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "schema": 1,
        "name": "demo",
        "sections": [
            {
                "key": "main",
                "title": "Main",
                "fields": [{"key": "name", "widget": "text", "label": "Name"}],
            }
        ],
    }
    form.update(more)
    return form


def _with_field(**field: Any) -> dict[str, Any]:
    form = _form()
    form["sections"][0]["fields"].append(
        {"key": "other", "widget": "text", "label": "Other", **field}
    )
    return form


def test_the_shipped_forms_are_valid_and_the_guard_form_has_its_sections() -> None:
    shipped = forms.read_all()
    assert "guard" in shipped
    guard = shipped["guard"]
    assert [(s.key, s.column) for s in guard.sections] == [
        ("trigger", 1),
        ("then", 2),
        ("condition", "full"),
        ("escalation", 1),
        ("logic", 2),
    ]
    assert guard.width == 50 and guard.columns == 2
    advanced = {f.key for s in guard.sections for f in s.fields if f.advanced}
    assert advanced == {"trigger.for_seconds", "trigger.cooldown_seconds"}


def test_every_widget_a_shipped_form_names_is_one_the_browser_registers() -> None:
    registered: set[str] = set()
    for path in (JS / "components" / "form-widgets.js", JS / "guards" / "widgets.js"):
        registered |= set(
            re.findall(r'registerWidget\("([a-z-]+)"', path.read_text(encoding="utf-8"))
        )
    for form in forms.FORMS.values():
        for section in form.sections:
            for field in section.fields:
                assert field.widget in registered, (
                    f"{form.name}.{field.key}: no JS widget {field.widget!r}"
                )
    assert set(forms.BUILT_IN_WIDGETS) <= registered


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (_with_field(widget="slider"), "unknown widget 'slider'"),
        (_with_field(key="name"), "field keys must be unique"),
        (_with_field(key="Bad Key"), "lowercase words joined by dots"),
        (_with_field(visible_when={"field": "nowhere", "equals": "x"}), "which is no field"),
        (_with_field(visible_when={"field": "other", "equals": "x"}), "names the field itself"),
        (_with_field(visible_when={"field": "name"}), "name one of equals or in"),
        (_with_field(widget="select"), "needs options"),
        (_with_field(options=[{"value": "a", "label": "A"}]), "takes no options"),
        (_with_field(advanced=True, required=True), "required field cannot be advanced"),
        (_with_field(min=5, max=1), "min is above max"),
        (_form(columns=3), "columns"),
        (_form(width=10), "width"),
        (
            _form(
                sections=[
                    {
                        "key": "a",
                        "title": "A",
                        "column": 3,
                        "fields": [{"key": "x", "widget": "text", "label": "X"}],
                    }
                ]
            ),
            "column",
        ),
        (_form(name="other"), "the file is named 'demo' but the form is 'other'"),
        (_form(extra=1), "extra"),
        (_form(schema=2), "schema must be 1"),
        (_form(sections=[]), "sections"),
    ],
)
def test_a_bad_form_is_refused_with_its_file_name(
    tmp_path: Path, data: dict[str, Any], why: str
) -> None:
    path = _write(tmp_path, "demo", data)
    with pytest.raises(FormError, match=re.escape("demo.yaml")) as caught:
        forms.read(path)
    assert why in str(caught.value)


def test_a_file_that_is_not_a_mapping_or_not_yaml_is_refused_with_its_name(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(FormError, match=r"list\.yaml: a form manifest is a mapping"):
        forms.read(tmp_path / "list.yaml")
    (tmp_path / "broken.yaml").write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(FormError, match=r"broken\.yaml: cannot be read"):
        forms.read(tmp_path / "broken.yaml")


def test_a_widget_a_third_party_registers_may_be_named_and_a_bad_name_is_refused(
    tmp_path: Path,
) -> None:
    data = _with_field(widget="colour-picker")
    with pytest.raises(FormError, match="unknown widget"):
        forms.read(_write(tmp_path, "demo", data))
    forms.register_widget("colour-picker")
    try:
        assert (
            forms.read(_write(tmp_path, "demo", data)).sections[0].fields[1].widget
            == "colour-picker"
        )
    finally:
        forms.CUSTOM_WIDGETS.discard("colour-picker")
    with pytest.raises(ValueError, match="lowercase letters"):
        forms.register_widget("Bad Name")


def test_the_forms_endpoint_serves_the_manifest_in_english_and_404s_for_an_unknown_form(
    client: TestClient,
) -> None:
    listed = client.get("/api/forms").json()
    assert [f["name"] for f in listed] == ["guard"]
    guard = client.get("/api/forms/guard").json()
    assert guard["schema"] == 1 and guard["columns"] == 2 and guard["width"] == 50
    trigger = guard["sections"][0]
    assert trigger["title"] == "Trigger" and trigger["column"] == 1
    events = next(f for f in trigger["fields"] if f["key"] == "trigger.events")
    assert [o["label"] for o in events["options"]][:2] == [
        "Entered (each round)",
        "An action passed",
    ]
    assert events["visible_when"] == {"field": "trigger.type", "equals": "event"}
    missing = client.get("/api/forms/nowhere")
    assert missing.status_code == 404 and missing.json() == {"detail": "Unknown form"}


def test_the_forms_endpoint_speaks_german_where_there_is_a_translation(client: TestClient) -> None:
    de = client.get("/api/forms/guard", headers={"Accept-Language": "de"}).json()
    assert de["sections"][0]["title"] == "Auslöser"
    events = next(f for f in de["sections"][0]["fields"] if f["key"] == "trigger.events")
    assert events["label"] == "Ereignisse"
    assert events["options"][0] == {
        "value": "enter",
        "label": "Betreten (jede Runde)",
    }  # the value stays
    assert events["visible_when"] == {"field": "trigger.type", "equals": "event"}
    again = client.get(
        "/api/forms/guard", headers={"Accept-Language": "fr"}
    ).json()  # no French: English
    assert again["sections"][0]["title"] == "Trigger"


def test_a_text_the_language_does_not_override_stays_english() -> None:
    description = forms.describe(forms.FORMS["guard"])
    de = forms.localize(description, "de")
    assert (
        description["sections"][0]["title"] == "Trigger"
    )  # the English description itself is untouched
    only_english = {
        **description,
        "sections": [{**description["sections"][1], "title": "Brand new"}],
    }
    assert forms.localize({**only_english, "name": "guard"}, "de")["sections"][0]["title"] == "Dann"
    assert de["sections"][2]["fields"][0]["label"] == "Bedingung"


def test_the_german_overrides_of_forms_name_things_that_exist() -> None:
    de = json.loads((ROOT / "openartifact/i18n/locales/de.json").read_text(encoding="utf-8"))
    seen = 0
    for key in de:
        if not key.startswith("forms."):
            continue
        seen += 1
        _, name, kind, rest = key.split(".", 3)
        form = forms.FORMS.get(name)
        assert form is not None, f"{key}: no such form"
        if kind == "sections":
            section, field = rest.split(".", 1)
            assert field == "title", key
            assert section in {s.key for s in form.sections}, f"{key}: no such section"
            continue
        assert kind == "fields", key
        by_key = {f.key: f for s in form.sections for f in s.fields}
        match = re.fullmatch(r"(.+)\.(label|help|placeholder|options\.(.+))", rest)
        assert match, f"{key}: not a known override"
        field = by_key.get(match[1])
        assert field is not None, f"{key}: no such field"
        if match[3]:
            assert match[3] in {o.value for o in field.options}, f"{key}: no such option"
    assert seen > 20


def test_every_text_of_the_guard_form_has_a_german_override() -> None:
    """German is shipped complete (like the node kinds' texts that matter): a new English text of a form needs its German."""
    de = json.loads((ROOT / "openartifact/i18n/locales/de.json").read_text(encoding="utf-8"))
    missing = []
    for form in forms.FORMS.values():
        for section in form.sections:
            if f"forms.{form.name}.sections.{section.key}.title" not in de:
                missing.append(f"{form.name}.{section.key}.title")
            for field in section.fields:
                base = f"forms.{form.name}.fields.{field.key}"
                for name in ("label", "help"):
                    if getattr(field, name) and f"{base}.{name}" not in de:
                        missing.append(f"{base}.{name}")
                missing += [
                    f"{base}.options.{o.value}"
                    for o in field.options
                    if f"{base}.options.{o.value}" not in de
                ]
    assert missing == [], f"German lacks form texts: {missing}"

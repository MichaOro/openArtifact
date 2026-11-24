"""The layout layer of the manifest windows (ADR-063): where a window's sections and fields sit, as a customisation of the
shipped YAML manifest.

The shipped manifests (``ui/forms/*.yaml`` for the configuration windows, ``graph/nodes/*.yaml`` for the settings of a node
kind) live in the image and are never written. A user's arrangement is **a layer in the data store** (one JSON document per
window, in the ``app_settings`` row ``ui.layouts``) that is merged over the manifest when the browser asks for it. It holds
nothing but order: which sections go in which column and in what order, which fields follow in each section and which of
them are folded away (forms), or the order of the settings of the two sides of a node's window (nodes). Adding, removing,
hiding or renaming is not part of it.

A window is named ``forms/<form>`` or ``nodes/<kind>``. The merge is one pure function per kind of window
(:func:`apply_form_layout`, :func:`apply_node_layout`); a stored layout is *read forgivingly* (a key the manifest no longer
has is ignored, a key it gained since appears at its default place, so a manifest update never breaks a saved layout) and
*written strictly* (:func:`check_form_layout`, :func:`check_node_layout` refuse what they do not know).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import AppSetting

KEY = "ui.layouts"
WINDOW = re.compile(r"^(forms|nodes)/[a-z][a-z0-9_]*$")
NODE_SECTIONS = ("definition", "behaviour")
COLUMNS = (1, 2, "auto", "full")
MAX_ENTRIES = 200


class LayoutError(ValueError):
    """A layout is not valid; the message says what and where."""


# ── forms ─────────────────────────────────────────────────────────────


def shipped_form_layout(description: dict[str, Any]) -> dict[str, Any]:
    """The arrangement a form manifest has as shipped."""
    return {
        "sections": [
            {
                "key": s["key"],
                "column": s.get("column", "auto"),
                "fields": [f["key"] for f in s["fields"] if not f.get("advanced")],
                "advanced": [f["key"] for f in s["fields"] if f.get("advanced")],
            }
            for s in description["sections"]
        ]
    }


def _merge_order(shipped: list[str], saved: list[str]) -> list[str]:
    """The saved order of the keys the manifest still has; a key the layout does not know goes after the key before it in
    the manifest (or first)."""
    known = set(shipped)
    merged: list[str] = []
    for key in saved:
        if key in known and key not in merged:
            merged.append(key)
    previous: str | None = None
    for key in shipped:
        if key not in merged:
            merged.insert(0 if previous is None else merged.index(previous) + 1, key)
        previous = key
    return merged


def _saved_sections(layout: Any) -> list[dict[str, Any]]:
    sections = layout.get("sections") if isinstance(layout, dict) else None
    return [s for s in sections if isinstance(s, dict)] if isinstance(sections, list) else []


def apply_form_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    """The form description with the saved arrangement put over it (a copy). A layout that fits no section changes nothing."""
    saved = {s.get("key"): s for s in _saved_sections(layout)}
    out = copy.deepcopy(description)
    shipped = {s["key"]: s for s in out["sections"]}
    order = _merge_order(list(shipped), [str(s.get("key")) for s in _saved_sections(layout)])
    sections: list[dict[str, Any]] = []
    for key in order:
        section = shipped[key]
        mine = saved.get(key) or {}
        column = mine.get("column")
        if section.get("column") == "full":
            column = "full"
        elif column not in (1, 2, "auto"):
            column = section.get("column", "auto")
        section["column"] = column
        fields = {f["key"]: f for f in section["fields"]}
        shown = list(dict.fromkeys(k for k in mine.get("fields") or [] if k in fields))
        folded = list(
            dict.fromkeys(
                k
                for k in mine.get("advanced") or []
                if k in fields and k not in shown and not fields[k].get("required")
            )
        )
        flags = {**dict.fromkeys(shown, False), **dict.fromkeys(folded, True)}
        sequence = [*shown, *folded]
        previous: str | None = None
        for k in fields:  # what the layout does not know keeps its place after the field before it, and its own flag
            if k not in flags:
                sequence.insert(0 if previous is None else sequence.index(previous) + 1, k)
                flags[k] = bool(fields[k].get("advanced"))
            previous = k
        for k in sequence:
            fields[k]["advanced"] = flags[k]
        section["fields"] = [fields[k] for k in sequence]
        sections.append(section)
    out["sections"] = sections
    out["layout_customised"] = True
    return out


def check_form_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    """Refuse a form layout that names what the manifest does not have or breaks a rule of the window; returns it normalised."""
    if not isinstance(layout, dict) or not isinstance(layout.get("sections"), list):
        raise LayoutError("a layout is an object with a list of sections")
    unknown = set(layout) - {"sections"}
    if unknown:
        raise LayoutError(f"unknown key in the layout: {sorted(unknown)}")
    shipped = {s["key"]: s for s in description["sections"]}
    seen: set[str] = set()
    sections = []
    for entry in layout["sections"]:
        if not isinstance(entry, dict):
            raise LayoutError("a section of the layout is an object")
        extra = set(entry) - {"key", "column", "fields", "advanced"}
        if extra:
            raise LayoutError(f"unknown key in a section: {sorted(extra)}")
        key = str(entry.get("key"))
        if key not in shipped:
            raise LayoutError(f"unknown section {key!r}")
        if key in seen:
            raise LayoutError(f"section {key!r} is listed more than once")
        seen.add(key)
        column = entry.get("column", shipped[key].get("column", "auto"))
        if column not in COLUMNS:
            raise LayoutError(f"section {key!r}: the column is 1, 2 or auto, not {column!r}")
        if (column == "full") != (shipped[key].get("column") == "full"):
            raise LayoutError(
                f"section {key!r} is full width and stays full width"
                if shipped[key].get("column") == "full"
                else f"section {key!r} cannot become full width"
            )
        fields = {f["key"]: f for f in shipped[key]["fields"]}
        listed: list[str] = []
        for part in ("fields", "advanced"):
            keys = entry.get(part, [])
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise LayoutError(f"section {key!r}: {part} is a list of field keys")
            for field in keys:
                if field not in fields:
                    raise LayoutError(f"{field!r} is not a field of section {key!r}")
                if field in listed:
                    raise LayoutError(f"field {field!r} is listed more than once")
                if part == "advanced" and fields[field].get("required"):
                    raise LayoutError(f"field {field!r} is required and cannot be folded away")
                listed.append(field)
        sections.append(
            {
                "key": key,
                "column": column,
                "fields": list(entry.get("fields", [])),
                "advanced": list(entry.get("advanced", [])),
            }
        )
    return {"sections": sections}


# ── nodes ─────────────────────────────────────────────────────────────


def node_entries(description: dict[str, Any]) -> dict[str, list[str]]:
    """The entries of the window of a node kind per section, in manifest order: a setting is its key, the settings of one
    ``group`` that follow each other are one entry ``group:<name>`` (they move together)."""
    entries: dict[str, list[str]] = {}
    last: tuple[str, str] | None = None
    for setting in description.get("settings", []):
        section = setting.get("section") or "definition"
        group = setting.get("group")
        entry = f"group:{group}" if group else setting["key"]
        if group and last == (section, entry):
            continue
        entries.setdefault(section, []).append(entry)
        last = (section, entry) if group else None
    return entries


def shipped_node_layout(description: dict[str, Any]) -> dict[str, Any]:
    entries = node_entries(description)
    return {"sections": [{"key": s, "fields": entries[s]} for s in NODE_SECTIONS if s in entries]}


def apply_node_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    """The description of a node kind with its settings in the saved order and ``layout.sections`` naming the sides left
    to right (a copy)."""
    out = copy.deepcopy(description)
    entries = node_entries(description)
    saved = {s.get("key"): s for s in _saved_sections(layout)}
    order = _merge_order(
        [s for s in NODE_SECTIONS if s in entries],
        [str(s.get("key")) for s in _saved_sections(layout) if s.get("key") in entries],
    )
    by_entry: dict[str, list[dict[str, Any]]] = {}
    for setting in description.get("settings", []):
        section = setting.get("section") or "definition"
        group = setting.get("group")
        by_entry.setdefault(
            f"{section}:{f'group:{group}' if group else setting['key']}", []
        ).append(copy.deepcopy(setting))
    settings: list[dict[str, Any]] = []
    for section in order:
        mine = saved.get(section) or {}
        for entry in _merge_order(
            entries[section], [k for k in mine.get("fields") or [] if isinstance(k, str)]
        ):
            settings.extend(by_entry[f"{section}:{entry}"])
    out["settings"] = settings
    out["layout"] = {"sections": order}
    out["layout_customised"] = True
    return out


def check_node_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    if not isinstance(layout, dict) or not isinstance(layout.get("sections"), list):
        raise LayoutError("a layout is an object with a list of sections")
    unknown = set(layout) - {"sections"}
    if unknown:
        raise LayoutError(f"unknown key in the layout: {sorted(unknown)}")
    entries = node_entries(description)
    seen: set[str] = set()
    sections = []
    for entry in layout["sections"]:
        if not isinstance(entry, dict):
            raise LayoutError("a section of the layout is an object")
        extra = set(entry) - {"key", "fields"}
        if extra:
            raise LayoutError(
                f"the window of a node has sections and fields only (a column or a folded group is not one): {sorted(extra)}"
            )
        key = str(entry.get("key"))
        if key not in entries:
            raise LayoutError(f"unknown section {key!r}")
        if key in seen:
            raise LayoutError(f"section {key!r} is listed more than once")
        seen.add(key)
        keys = entry.get("fields", [])
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise LayoutError(f"section {key!r}: fields is a list of settings")
        listed: list[str] = []
        for name in keys:
            if name not in entries[key]:
                raise LayoutError(f"{name!r} is not in section {key!r}")
            if name in listed:
                raise LayoutError(f"{name!r} is listed more than once")
            listed.append(name)
        sections.append({"key": key, "fields": listed})
    return {"sections": sections}


# ── windows and storage ───────────────────────────────────────────────


def shipped_layout(window: str, description: dict[str, Any]) -> dict[str, Any]:
    return (
        shipped_form_layout(description)
        if window.startswith("forms/")
        else shipped_node_layout(description)
    )


def apply_layout(window: str, description: dict[str, Any], layout: Any) -> dict[str, Any]:
    if layout is None:
        return description
    return (
        apply_form_layout(description, layout)
        if window.startswith("forms/")
        else apply_node_layout(description, layout)
    )


def check_layout(window: str, description: dict[str, Any], layout: Any) -> dict[str, Any]:
    return (
        check_form_layout(description, layout)
        if window.startswith("forms/")
        else check_node_layout(description, layout)
    )


def export_yaml(window: str, layout: dict[str, Any]) -> str:
    """The layout of a window as YAML, ready to be put into the repository as the new default (layout only: no texts, no
    values)."""
    header = (
        f"# The layout of the window {window}: the order of its sections and fields (ADR-063).\n"
        "# Merge it into the shipped manifest to make it the default.\n"
    )
    body: str = yaml.safe_dump(
        {"window": window, "layout": layout}, sort_keys=False, allow_unicode=True
    )
    return header + body


async def load_all(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(AppSetting, KEY)
    if row is None:
        return {}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def save_raw(session: AsyncSession, window: str, layout: dict[str, Any] | None) -> None:
    """Store (or, with ``None``, drop) the layout of one window; the caller commits."""
    layouts = await load_all(session)
    if layout is None:
        layouts.pop(window, None)
    else:
        layouts[window] = layout
    value = json.dumps(layouts)
    row = await session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value

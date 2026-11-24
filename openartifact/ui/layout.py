"""The layout layer of the manifest windows (ADR-063): where a window's sections and fields sit, as a customisation of the
shipped YAML manifest.

The shipped manifests (``ui/forms/*.yaml`` for the configuration windows, ``graph/nodes/*.yaml`` for the settings of a node
kind) live in the image and are never written. A user's arrangement is **a layer in the data store** (one JSON document per
window, in the ``app_settings`` row ``ui.layouts``) that is merged over the manifest when the browser asks for it. It holds
nothing but placement: which sections (areas) go in which column and in what order, which fields sit in each of them and
which of those are folded away (forms), or which settings sit in which area of a node's window and in what order (nodes).
A field or a setting may sit in ANY area, shipped or custom: it keeps its meaning, level and validation, only its place
changes. A user may add areas of their own (``custom_<id>``, a plain title of 1 to 40 characters, at most 12 per window): an
area is only a container. Adding or removing fields, hiding and renaming a field are not part of it.

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
CUSTOM = re.compile(r"^custom_[a-z0-9]{1,12}$")
MAX_CUSTOM = 12
TITLE_MAX = 40
#: Settings a node kind draws itself (the Agent node's choice of agent and its inputs): they are not entries, stay at the top
#: of the Definition area and cannot be arranged. The browser draws the same blocks (static/js/editor/node-layout.js).
FIXED_BLOCKS: dict[str, tuple[str, ...]] = {"agent": ("agent_id", "inputs")}


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


def _clean_title(value: Any) -> str | None:
    """A custom area's title as read forgivingly: a non-empty string, cut to the limit; anything else is no title."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:TITLE_MAX]


def _custom_areas(saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The custom areas of a stored layout, read forgivingly: valid key, usable title, first one wins, at most the limit."""
    found: list[dict[str, Any]] = []
    for entry in saved:
        key = entry.get("key")
        title = _clean_title(entry.get("title"))
        if (
            isinstance(key, str)
            and CUSTOM.fullmatch(key)
            and title
            and all(c["key"] != key for c in found)
            and len(found) < MAX_CUSTOM
        ):
            found.append({"key": key, "title": title, "column": entry.get("column")})
    return found


def _check_area(entry: dict[str, Any], shipped: set[str], custom_seen: int, where: str) -> str:
    """Strict checks of one area of a layout document: returns its key. A shipped area is neither renamed nor made up; a
    custom one has a valid key and a title."""
    key = str(entry.get("key"))
    if key in shipped:
        if "title" in entry:
            raise LayoutError(f"{where} {key!r} is shipped and cannot be renamed")
    elif CUSTOM.fullmatch(key):
        title = entry.get("title")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= TITLE_MAX:
            raise LayoutError(f"the title of area {key!r} is 1 to {TITLE_MAX} characters")
        if custom_seen >= MAX_CUSTOM:
            raise LayoutError(f"a window has at most {MAX_CUSTOM} areas of your own")
    else:
        raise LayoutError(f"unknown {where} {key!r}")
    return key


def apply_form_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    """The form description with the saved arrangement put over it (a copy). A layout that fits no section changes nothing.

    A field may sit in any section (shipped or custom). Sections without a field are not part of ``sections`` (the form does
    not draw them); ``layout.areas`` names every area in order, empty ones too, for the arrange view."""
    saved = _saved_sections(layout)
    out = copy.deepcopy(description)
    shipped = {s["key"]: s for s in out["sections"]}
    where = {f["key"]: (s["key"], f) for s in out["sections"] for f in s["fields"]}
    custom = _custom_areas(saved)
    custom_by = {c["key"]: c for c in custom}
    known = [*shipped, *custom_by]
    order = _merge_order(
        known,
        [str(s.get("key")) for s in saved if isinstance(s.get("key"), str) and s["key"] in known],
    )
    sequence: dict[str, list[str]] = {a: [] for a in known}
    flags: dict[str, bool] = {}
    placed: set[str] = set()
    for entry in saved:
        area = entry.get("key")
        if area not in sequence:
            continue
        shown = [
            k
            for k in entry.get("fields") or []
            if isinstance(k, str) and k in where and k not in placed
        ]
        placed.update(shown)
        folded = [
            k
            for k in entry.get("advanced") or []
            if isinstance(k, str)
            and k in where
            and k not in placed
            and not where[k][1].get("required")
        ]
        placed.update(folded)
        sequence[area] += [*shown, *folded]
        flags.update(dict.fromkeys(shown, False))
        flags.update(dict.fromkeys(folded, True))
    for section in out[
        "sections"
    ]:  # what the layout does not know keeps its place after the field before it, its own flag
        previous: str | None = None
        for field in section["fields"]:
            key = field["key"]
            if key not in placed:
                lane = sequence[section["key"]]
                lane.insert(
                    0 if previous is None or previous not in lane else lane.index(previous) + 1, key
                )
                flags[key] = bool(field.get("advanced"))
            previous = key
    sections: list[dict[str, Any]] = []
    areas: list[dict[str, Any]] = []
    for area in order:
        mine = next((s for s in saved if s.get("key") == area), {})
        if area in shipped:
            column = mine.get("column")
            if shipped[area].get("column") == "full":
                column = "full"
            elif column not in (1, 2, "auto"):
                column = shipped[area].get("column", "auto")
            section = shipped[area]
            section["column"] = column
        else:
            column = (
                custom_by[area]["column"] if custom_by[area]["column"] in (1, 2, "auto") else "auto"
            )
            section = {"key": area, "title": custom_by[area]["title"], "column": column}
        areas.append(
            {
                "key": area,
                "title": section.get("title"),
                "column": column,
                "custom": area not in shipped,
            }
        )
        fields = []
        for key in sequence[area]:
            field = where[key][1]
            field["advanced"] = flags[key]
            fields.append(field)
        section["fields"] = fields
        if fields:
            sections.append(section)
    out["sections"] = sections
    out["layout"] = {"areas": areas}
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
    fields = {f["key"]: f for s in description["sections"] for f in s["fields"]}
    seen: set[str] = set()
    listed: set[str] = set()
    custom = 0
    sections = []
    for entry in layout["sections"]:
        if not isinstance(entry, dict):
            raise LayoutError("a section of the layout is an object")
        extra = set(entry) - {"key", "column", "fields", "advanced", "title"}
        if extra:
            raise LayoutError(f"unknown key in a section: {sorted(extra)}")
        key = _check_area(entry, set(shipped), custom, "section")
        if key not in shipped:
            custom += 1
        if key in seen:
            raise LayoutError(f"section {key!r} is listed more than once")
        seen.add(key)
        default = shipped[key].get("column", "auto") if key in shipped else "auto"
        column = entry.get("column", default)
        if column not in COLUMNS:
            raise LayoutError(f"section {key!r}: the column is 1, 2 or auto, not {column!r}")
        if (column == "full") != (default == "full"):
            raise LayoutError(
                f"section {key!r} is full width and stays full width"
                if default == "full"
                else f"section {key!r} cannot become full width"
            )
        for part in ("fields", "advanced"):
            keys = entry.get(part, [])
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise LayoutError(f"section {key!r}: {part} is a list of field keys")
            for field in keys:
                if field not in fields:
                    raise LayoutError(f"{field!r} is not a field of this form")
                if field in listed:
                    raise LayoutError(f"field {field!r} is listed more than once")
                if part == "advanced" and fields[field].get("required"):
                    raise LayoutError(f"field {field!r} is required and cannot be folded away")
                listed.add(field)
        item: dict[str, Any] = {
            "key": key,
            "column": column,
            "fields": list(entry.get("fields", [])),
            "advanced": list(entry.get("advanced", [])),
        }
        if key not in shipped:
            item["title"] = str(entry["title"]).strip()
        sections.append(item)
    return {"sections": sections}


def current_form_layout(description: dict[str, Any]) -> dict[str, Any]:
    """The arrangement a (merged) form description has now, custom and empty areas included."""
    areas = (description.get("layout") or {}).get("areas")
    if areas is None:
        return shipped_form_layout(description)
    by_key = {s["key"]: s for s in description["sections"]}
    sections = []
    for area in areas:
        mine = by_key.get(area["key"], {"fields": []})
        item: dict[str, Any] = {
            "key": area["key"],
            "column": area["column"],
            "fields": [f["key"] for f in mine["fields"] if not f.get("advanced")],
            "advanced": [f["key"] for f in mine["fields"] if f.get("advanced")],
        }
        if area["custom"]:
            item["title"] = area["title"]
        sections.append(item)
    return {"sections": sections}


# ── nodes ─────────────────────────────────────────────────────────────


def _node_model(
    description: dict[str, Any],
) -> tuple[list[str], dict[str, str], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """The entries of the window of a node kind in manifest order, the area each is shipped in, the settings of each entry
    and the settings the kind draws itself. An entry is a setting's key; the settings of one ``group`` are one entry
    ``group:<name>`` (they move together)."""
    fixed_keys = set(FIXED_BLOCKS.get(str(description.get("kind")), ()))
    order: list[str] = []
    shipped: dict[str, str] = {}
    members: dict[str, list[dict[str, Any]]] = {}
    fixed: list[dict[str, Any]] = []
    for setting in description.get("settings", []):
        if setting["key"] in fixed_keys:
            fixed.append(setting)
            continue
        group = setting.get("group")
        entry = f"group:{group}" if group else setting["key"]
        members.setdefault(entry, []).append(setting)
        if entry not in shipped:
            shipped[entry] = setting.get("section") or "definition"
            order.append(entry)
    return order, shipped, members, fixed


def node_entries(description: dict[str, Any]) -> dict[str, list[str]]:
    """The entries of the window of a node kind per area, in manifest order (the settings the kind draws itself are none)."""
    order, shipped, _, _ = _node_model(description)
    entries: dict[str, list[str]] = {}
    for entry in order:
        entries.setdefault(shipped[entry], []).append(entry)
    return entries


def shipped_node_layout(description: dict[str, Any]) -> dict[str, Any]:
    entries = node_entries(description)
    return {"sections": [{"key": s, "fields": entries[s]} for s in NODE_SECTIONS if s in entries]}


def apply_node_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    """The description of a node kind with its settings placed as saved (a copy): each setting's ``section`` is the area it
    now sits in, ``layout.sections`` names the areas in order (custom ones, empty ones too) and ``layout.titles`` the titles
    of the custom ones."""
    out = copy.deepcopy(description)
    order, shipped, members, fixed = _node_model(description)
    saved = _saved_sections(layout)
    custom = _custom_areas(saved)
    known = [*NODE_SECTIONS, *[c["key"] for c in custom]]
    lists: dict[str, list[str]] = {a: [] for a in known}
    placed: set[str] = set()
    for entry in saved:
        area = entry.get("key")
        if area not in lists:
            continue
        for name in entry.get("fields") or []:
            if isinstance(name, str) and name in members and name not in placed:
                placed.add(name)
                lists[area].append(name)
    for at, name in enumerate(
        order
    ):  # what the layout does not know goes after the entry before it, in its shipped area
        if name in placed:
            continue
        lane = lists[shipped[name] if shipped[name] in lists else "definition"]
        before = next((p for p in reversed(order[:at]) if p in lane), None)
        lane.insert(0 if before is None else lane.index(before) + 1, name)
    saved_keys = [s["key"] for s in saved if isinstance(s.get("key"), str) and s["key"] in lists]
    areas = _merge_order(
        [*[a for a in NODE_SECTIONS if lists[a] or a in saved_keys], *[c["key"] for c in custom]],
        saved_keys,
    )
    settings = [copy.deepcopy(s) for s in fixed]
    for area in areas:
        for name in lists[area]:
            for setting in members[name]:
                moved = copy.deepcopy(setting)
                moved["section"] = area
                settings.append(moved)
    out["settings"] = settings
    out["layout"] = {"sections": areas}
    if custom:
        out["layout"]["titles"] = {c["key"]: c["title"] for c in custom}
    out["layout_customised"] = True
    return out


def check_node_layout(description: dict[str, Any], layout: Any) -> dict[str, Any]:
    if not isinstance(layout, dict) or not isinstance(layout.get("sections"), list):
        raise LayoutError("a layout is an object with a list of sections")
    unknown = set(layout) - {"sections"}
    if unknown:
        raise LayoutError(f"unknown key in the layout: {sorted(unknown)}")
    _, _, members, fixed = _node_model(description)
    fixed_keys = {s["key"] for s in fixed}
    seen: set[str] = set()
    listed: set[str] = set()
    custom = 0
    sections = []
    for entry in layout["sections"]:
        if not isinstance(entry, dict):
            raise LayoutError("a section of the layout is an object")
        extra = set(entry) - {"key", "fields", "title"}
        if extra:
            raise LayoutError(
                f"the window of a node has areas and settings only (a column or a folded group is not one): {sorted(extra)}"
            )
        key = _check_area(entry, set(NODE_SECTIONS), custom, "section")
        if key not in NODE_SECTIONS:
            custom += 1
        if key in seen:
            raise LayoutError(f"section {key!r} is listed more than once")
        seen.add(key)
        keys = entry.get("fields", [])
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise LayoutError(f"section {key!r}: fields is a list of settings")
        for name in keys:
            if name in fixed_keys:
                raise LayoutError(f"{name!r} is drawn by the kind itself and stays where it is")
            if name not in members:
                raise LayoutError(f"{name!r} is not a setting of this kind")
            if name in listed:
                raise LayoutError(f"{name!r} is listed more than once")
            listed.add(name)
        item: dict[str, Any] = {"key": key, "fields": list(keys)}
        if key not in NODE_SECTIONS:
            item["title"] = str(entry["title"]).strip()
        sections.append(item)
    return {"sections": sections}


def current_node_layout(description: dict[str, Any]) -> dict[str, Any]:
    """The arrangement a (merged) node description has now: its areas in order with the entries each holds."""
    saved = description.get("layout") or {}
    entries = node_entries(description)
    areas = saved.get("sections") or [s for s in NODE_SECTIONS if s in entries]
    titles = saved.get("titles") or {}
    sections = []
    for area in areas:
        item: dict[str, Any] = {"key": area, "fields": entries.get(area, [])}
        if area in titles:
            item["title"] = titles[area]
        sections.append(item)
    return {"sections": sections}


# ── windows and storage ───────────────────────────────────────────────


def shipped_layout(window: str, description: dict[str, Any]) -> dict[str, Any]:
    return (
        shipped_form_layout(description)
        if window.startswith("forms/")
        else shipped_node_layout(description)
    )


def current_layout(window: str, description: dict[str, Any]) -> dict[str, Any]:
    """The layout a merged description has now (custom and empty areas included)."""
    return (
        current_form_layout(description)
        if window.startswith("forms/")
        else current_node_layout(description)
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

"""The texts of the node kinds in the user's language (ADR-056).

The manifests (``graph/nodes/*.yaml``) are the English source. A locale file may override single texts by key; whatever it
does not override stays the manifest's English text:

* ``nodes.<kind>.label`` the kind's name; ``nodes.<kind>.caption`` the caption template of its card (translators copy the
  template and translate the fixed words around the ``{...}`` parts)
* ``nodes.<kind>.settings.<key>.label`` / ``.help`` / ``.placeholder``, and ``.options.<value>`` the shown text of one
  option of a select (the stored value stays what the manifest says)
* ``nodes.<kind>.ports.<name>`` the label of a port
* ``nodes.menu.<group>`` a cluster of the "+" menu
* ``nodes.placeholders.<key>.label`` the name of a placeholder entry of the "+" menu (``_menu.yaml``)
"""

from __future__ import annotations

import copy
from typing import Any

from openartifact import i18n
from openartifact.graph.manifest import menu_groups, read_placeholders


def _own(language: str, key: str) -> str | None:
    """The text of ``key`` in ``language`` only (English files do not hold manifest texts, so there is no fallback to
    anything but the manifest)."""
    if language == i18n.DEFAULT_LANGUAGE or language not in i18n.languages():
        return None
    return i18n.messages(language).get(key)


def localize(description: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """The node-type descriptions with the language's overrides put in (a copy; English: the descriptions as they are)."""
    if language == i18n.DEFAULT_LANGUAGE or language not in i18n.languages():
        return description
    out = copy.deepcopy(description)
    for entry in out:
        kind = entry["kind"]
        entry["label"] = _own(language, f"nodes.{kind}.label") or entry["label"]
        menu = entry.get("menu")
        if menu and (text := _own(language, f"nodes.menu.{menu['group']}")):
            menu["group"] = text
        ui = entry.get("ui") or {}
        caption = ui.get("caption")
        if isinstance(caption, dict) and (text := _own(language, f"nodes.{kind}.caption")):
            caption["template"] = text
        if ui.get("hint") and (text := _own(language, f"nodes.{kind}.hint")):
            ui["hint"] = text
        for port in (*entry.get("inputs", []), *entry.get("outputs", [])):
            port["label"] = _own(language, f"nodes.{kind}.ports.{port['name']}") or port["label"]
        for setting in entry.get("settings", []):
            base = f"nodes.{kind}.settings.{setting['key']}"
            for field in ("label", "help", "placeholder"):
                if text := _own(language, f"{base}.{field}"):
                    setting[field] = text
            labels = {
                option: text
                for option in setting.get("options") or []
                if (text := _own(language, f"{base}.options.{option}"))
            }
            if labels:  # an option the language does not name keeps its English text
                setting["option_labels"] = {**(setting.get("option_labels") or {}), **labels}
    return out


def placeholders(language: str) -> list[dict[str, Any]]:
    """The placeholder entries of the "+" menu (``_menu.yaml``) in the user's language, for the editor page: each with its
    cluster, the cluster's place and its own place in it. They are no kinds of nodes and create nothing."""
    groups = menu_groups()
    out = []
    for spec in read_placeholders():
        entry = spec.model_dump()
        entry["group_index"] = groups.index(spec.group)
        entry["label"] = _own(language, f"nodes.placeholders.{spec.key}.label") or spec.label
        entry["group"] = _own(language, f"nodes.menu.{spec.group}") or spec.group
        out.append(entry)
    return out

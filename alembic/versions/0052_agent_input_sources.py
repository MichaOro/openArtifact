"""Every input of an agent has a source: a value or the artifact (ADR-064, revised).

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-24

An input of an agent said ``type`` (``string``, ``number``, ``boolean`` or ``artifact``). It now says where its value comes
from: ``source`` is ``value`` (with a ``type``, mapped in the action's node) or ``artifact`` (with a ``part`` of the
artifact the run belongs to: the definition fixes it, so the node maps nothing and it has no required flag and no
default). This rewrites, in the draft of every agent and in every published version:

* an input of the type ``artifact`` into the source ``artifact`` with the part ``title_body`` (what ``${card.text}``
  was), without required and default,
* every other input into the source ``value`` with its type,

and removes from the mapping of every agent node (``graph_nodes.config.inputs``, lines ``name = value``) the lines of the
inputs that now come from the artifact, because the node can no longer map them. Only JSON text changes, no table is
rebuilt (see 0043). The downgrade turns the sources back into types (every artifact input becomes ``artifact``); the
mapping lines that were removed are not restored.
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def _forward(inputs: Any) -> tuple[list[Any], bool]:
    """The inputs in the new shape and whether anything changed."""
    if not isinstance(inputs, list):
        return [], False
    changed = False
    out: list[Any] = []
    for spec in inputs:
        if not isinstance(spec, dict):
            out.append(spec)
            continue
        new = dict(spec)
        if spec.get("type") == "artifact" or spec.get("source") == "artifact":
            new.update(
                {
                    "source": "artifact",
                    "type": None,
                    "part": spec.get("part") or "title_body",
                    "required": False,
                    "default": None,
                }
            )
        else:
            new.update({"source": "value", "type": spec.get("type") or "string", "part": None})
        changed = changed or new != spec
        out.append(new)
    return out, changed


def _back(inputs: Any) -> tuple[list[Any], bool]:
    if not isinstance(inputs, list):
        return [], False
    changed = False
    out: list[Any] = []
    for spec in inputs:
        if not isinstance(spec, dict):
            out.append(spec)
            continue
        new = {k: v for k, v in spec.items() if k not in ("source", "part")}
        if spec.get("source") == "artifact":
            new["type"] = "artifact"
            new["required"] = False
            new["default"] = None
        else:
            new["type"] = spec.get("type") or "string"
        changed = changed or new != spec
        out.append(new)
    return out, changed


def _rewrite(raw: str | None, convert: Any) -> tuple[str | None, list[Any], bool]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return raw, [], False
    if not isinstance(data, dict) or "inputs" not in data:
        return raw, [], False
    inputs, changed = convert(data["inputs"])
    if not changed:
        return raw, inputs, False
    data["inputs"] = inputs
    return json.dumps(data, ensure_ascii=False, sort_keys=True), inputs, True


def _artifact_names(inputs: list[Any]) -> set[str]:
    return {
        str(s["name"])
        for s in inputs
        if isinstance(s, dict) and s.get("source") == "artifact" and "name" in s
    }


def _without(text: str, names: set[str]) -> tuple[str, int]:
    """The mapping text without the lines of ``names``, and how many lines were taken out."""
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        name = line.partition("=")[0].strip()
        name = name[len("input.") :] if name.startswith("input.") else name
        if "=" in line and name in names:
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), removed


def upgrade() -> None:
    bind = op.get_bind()
    drafts = versions = lines = 0
    published_names: dict[str, set[str]] = {}
    for agent_id, draft, number in bind.execute(
        sa.text("SELECT id, draft, published_number FROM agents")
    ).fetchall():
        new_draft, draft_inputs, changed = _rewrite(draft, _forward)
        if changed:
            bind.execute(
                sa.text("UPDATE agents SET draft = :d WHERE id = :i"),
                {"d": new_draft, "i": agent_id},
            )
            drafts += 1
        names = _artifact_names(draft_inputs)
        for version_id, version_number, config in bind.execute(
            sa.text("SELECT id, number, config FROM agent_versions WHERE agent_id = :i"),
            {"i": agent_id},
        ).fetchall():
            new_config, version_inputs, changed = _rewrite(config, _forward)
            if changed:
                bind.execute(
                    sa.text("UPDATE agent_versions SET config = :c WHERE id = :v"),
                    {"c": new_config, "v": version_id},
                )
                versions += 1
            if version_number == number:
                names = _artifact_names(version_inputs)  # a node runs the published version
        published_names[agent_id] = names
    for node_id, raw in bind.execute(
        sa.text("SELECT id, config FROM graph_nodes WHERE kind = 'agent'")
    ).fetchall():
        try:
            config = json.loads(raw or "{}")
        except ValueError:
            continue
        if not isinstance(config, dict) or not isinstance(config.get("inputs"), str):
            continue
        names = published_names.get(str(config.get("agent_id")), set())
        text, removed = _without(config["inputs"], names) if names else (config["inputs"], 0)
        if not removed:
            continue
        if text.strip():
            config["inputs"] = text
        else:
            config.pop("inputs")
        bind.execute(
            sa.text("UPDATE graph_nodes SET config = :c WHERE id = :n"),
            {"c": json.dumps(config, ensure_ascii=False), "n": node_id},
        )
        lines += removed
    log.info(
        "0052: input sources written for %d drafts and %d versions; %d mapping lines of nodes removed",
        drafts,
        versions,
        lines,
    )


def downgrade() -> None:
    bind = op.get_bind()
    for agent_id, draft in bind.execute(sa.text("SELECT id, draft FROM agents")).fetchall():
        new, _, changed = _rewrite(draft, _back)
        if changed:
            bind.execute(
                sa.text("UPDATE agents SET draft = :d WHERE id = :i"), {"d": new, "i": agent_id}
            )
    for version_id, config in bind.execute(
        sa.text("SELECT id, config FROM agent_versions")
    ).fetchall():
        new, _, changed = _rewrite(config, _back)
        if changed:
            bind.execute(
                sa.text("UPDATE agent_versions SET config = :c WHERE id = :v"),
                {"c": new, "v": version_id},
            )

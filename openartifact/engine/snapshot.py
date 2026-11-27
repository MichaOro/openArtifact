"""A frozen copy of a pipeline and the action definitions it uses.

Every graph is read through ``graph_for_run``: its published version when it has one, else its draft (ADR-070).

Every graph in it carries its ``id``, ``name`` and ``kind``; nodes carry their size and ``fail_enabled``,
edges their ``id``, style and slots, so the execution flow can draw it like the editor does. An agent
node also carries ``agent``: its agent as it was published when the snapshot was taken, with the
provider, the model and the node's overrides resolved (``agents/freeze.py``). ``guards`` and ``guard_definitions``
are the enabled guards of the pipelines and their own actions (ADR-060). Snapshots
frozen before those fields existed lack them; :mod:`openartifact.engine.flow` fills them in.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents.freeze import freeze_agents
from openartifact.graph.publishing import graph_for_run
from openartifact.models import (
    Graph,
    GuardAttachment,
    GuardDefinition,
    GuardVersion,
    NodeKind,
)

MAX_NESTING = 5  # pipelines calling pipelines calling ...


class NestingError(ValueError):
    """The pipeline calls itself or nests too deeply to be frozen."""


async def _collect(
    session: AsyncSession,
    root: dict[str, Any],
    graph: dict[str, Any],
    path: tuple[str, ...],
    draft: bool = False,
) -> None:
    """Add the action definitions and the called pipelines (recursively) of ``graph`` to ``root``."""
    for node in graph["nodes"]:
        target = node["definition_id"]
        if not target:
            continue
        if node["kind"] == NodeKind.ACTION and target not in root["definitions"]:
            root["definitions"][target] = await graph_for_run(session, target, draft=draft)
        elif node["kind"] == NodeKind.PIPELINE:
            if target in path:
                raise NestingError("The pipeline calls itself")
            if len(path) >= MAX_NESTING:
                raise NestingError("Pipelines are nested too deeply")
            if target not in root["pipelines"]:
                called = await graph_for_run(session, target, draft=draft)
                root["pipelines"][target] = called
                await _collect(session, root, called, (*path, target), draft)


async def build_snapshot(
    session: AsyncSession, graph: Graph, *, draft: bool = False
) -> dict[str, Any]:
    """The pipeline's graph plus the called pipelines and action definitions it uses, frozen: each in the version that runs, or with
    ``draft`` (a dry run that tests what is being edited, ADR-086) each in its draft."""
    snapshot = await graph_for_run(session, graph.id, draft=draft)
    snapshot["definitions"] = {}
    snapshot["pipelines"] = {}
    await _collect(session, snapshot, snapshot, (graph.id,), draft)
    await freeze_agents(session, snapshot)  # agent nodes keep the version they start with
    await freeze_guards(session, snapshot)
    return snapshot


_STANDALONE = uuid.UUID("5d0b2c1e-6a53-4c8e-9f0a-4f6f8f3b7a11")


def _wrapper_id(action_id: str, part: str) -> str:
    return str(uuid.uuid5(_STANDALONE, f"{action_id}:{part}"))


def wrap_action(definition: dict[str, Any]) -> dict[str, Any]:
    """The pipeline-shaped root of a dry run of one action definition (ADR-089): a Trigger, one stage holding one placement of the
    action, and a Complete, with the ids made from the action's id so the same run always has the same ones. The engine walks it like
    any pipeline, so the run is the action's own nodes, from its Trigger to its Output, and nothing around it. The wrapper is never
    stored as a graph; it exists in the snapshot of the run (``standalone`` names the action)."""
    action_id = str(definition["id"])
    trigger, stage, place, complete = (
        _wrapper_id(action_id, part) for part in ("trigger", "stage", "action", "complete")
    )

    def node(node_id: str, kind: str, name: str, **more: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": node_id, "kind": kind, "stage_id": None, "name": name, "label": name, "definition_id": None, "seconds": None,
            "config": {}, "number": None, "x": 0.0, "y": 0.0, "width": None, "height": None, "fail_enabled": False,
        }  # fmt: skip
        return base | more

    def edge(source: str, port: str, target: str, target_port: str) -> dict[str, Any]:
        return {
            "id": _wrapper_id(action_id, f"{source}>{target}"), "style": "curved", "source_slot": 0, "target_slot": 0,
            "source_id": source, "source_port": port, "target_id": target, "target_port": target_port,
        }  # fmt: skip

    name = str(definition["name"])
    return {
        "id": _wrapper_id(
            action_id, "pipeline"
        ),  # not the action's own id: the flow keeps its graphs by id, and the action is one of them
        "name": name,
        "kind": "pipeline",
        "standalone": action_id,
        "nodes": [
            node(trigger, NodeKind.TRIGGER, "Trigger", x=0.0, y=40.0),
            node(stage, NodeKind.STAGE, "Dry run", x=160.0, y=0.0, width=360.0, height=160.0),
            node(
                place,
                NodeKind.ACTION,
                name,
                stage_id=stage,
                definition_id=action_id,
                x=24.0,
                y=48.0,
            ),
            node(complete, NodeKind.COMPLETE, "Complete", x=600.0, y=40.0),
        ],
        "edges": [
            edge(trigger, "out", stage, "in"),
            edge(stage, "end", complete, "in"),
            edge(place, "pass", complete, "in"),
        ],
    }


async def build_action_snapshot(
    session: AsyncSession, action: Graph, *, draft: bool = False
) -> dict[str, Any]:
    """The snapshot of a dry run of one action definition (ADR-089): the wrapper of :func:`wrap_action` plus the definition in the version
    asked for (its draft, or the version that runs) and what that uses (called pipelines are not part of an action; its agents and
    guards are frozen like a pipeline's)."""
    definition = await graph_for_run(session, action.id, draft=draft)
    snapshot = wrap_action(definition)
    snapshot["definitions"] = {}
    snapshot["pipelines"] = {}
    await _collect(session, snapshot, snapshot, (action.id,), draft)
    await freeze_agents(session, snapshot)
    await freeze_guards(session, snapshot)
    return snapshot


async def freeze_guards(session: AsyncSession, snapshot: dict[str, Any]) -> None:
    """The switched-on guard attachments of the pipeline, of the pipelines it calls and of the action definitions the run
    uses (the whole action and its nodes), each with the **published version** of its definition (``guards``; ``version`` says
    which), and the guards' own actions (``guard_definitions``, apart from ``definitions`` so their node names never clash with the
    run's references). A definition that was never published watches nothing (ADR-081). A change to a definition, a publication or
    a change of an attachment after the start does not reach the run; only switching an attachment off does, at once, through the
    monitor's live check. A snapshot frozen before ADR-081 holds the definitions as they were and has no ``version``."""
    pipelines = [snapshot["id"], *snapshot.get("pipelines", {}), *snapshot.get("definitions", {})]
    rows = (
        await session.execute(
            select(GuardAttachment, GuardDefinition, GuardVersion)
            .join(GuardDefinition, GuardDefinition.id == GuardAttachment.guard_id)
            .join(
                GuardVersion,
                (GuardVersion.guard_id == GuardDefinition.id)
                & (GuardVersion.number == GuardDefinition.published_number),
            )
            .where(GuardAttachment.graph_id.in_(pipelines), GuardAttachment.enabled.is_(True))
            .order_by(GuardDefinition.name, GuardAttachment.id)
        )
    ).all()
    found = [
        (attachment, definition, json.loads(version.content), version.number)
        for attachment, definition, version in rows
    ]
    found.sort(key=lambda f: (str(f[2].get("name", "")), f[0].id))
    snapshot["guards"] = [
        guard_data(definition.id, content, attachment, number)
        for attachment, definition, content, number in found
    ]
    bodies: dict[str, Any] = {}
    for _attachment, _definition, content, _number in found:
        action_id = content.get("action_id")
        if action_id and action_id not in bodies:
            bodies[action_id] = await graph_for_run(session, action_id)
    snapshot["guard_definitions"] = bodies
    await freeze_agents(session, {"definitions": bodies})


def definition_data(row: GuardDefinition) -> dict[str, Any]:
    """A guard definition with its JSON columns parsed."""
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "scope_types": json.loads(row.scope_types or "[]"),
        "trigger": json.loads(row.trigger or "{}"),
        "when": json.loads(row.condition or "{}"),
        "consequence": row.consequence,
        "fallback": row.fallback,
        "escalation": json.loads(row.escalation or "[]"),
        "action_id": row.action_id,
    }


def guard_data(
    guard_id: str, content: dict[str, Any], attachment: GuardAttachment, version: int | None
) -> dict[str, Any]:
    """A guard as the engine carries it: one attachment with its published definition (``content``, what ``guards/versions.py``
    holds). ``id`` is the attachment's (the counters and the live on/off check are per place), ``guard_id`` the definition's,
    ``version`` the published version it froze and ``definition_id`` its own action (the key frozen executions have always had)."""
    return {
        "id": attachment.id,
        "guard_id": guard_id,
        "version": version,
        "graph_id": attachment.graph_id,
        "pipeline_id": attachment.graph_id,
        "name": content.get("name", ""),
        "scope_type": attachment.scope_type,
        "scope_id": attachment.scope_id,
        "trigger": content.get("trigger", {}),
        "when": content.get("when", {}),
        "consequence": content.get("consequence", "pause"),
        "fallback": content.get("fallback", "pause"),
        "escalation": content.get("escalation", []),
        "definition_id": content.get("action_id"),
        "enabled": attachment.enabled,
    }

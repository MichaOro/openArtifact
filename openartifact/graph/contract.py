"""The contract of an action or a pipeline: the inputs its Trigger declares and the outputs its Output (action) or Complete (pipeline) declares
(ADR-083), read from **the version that runs**.

An execution reads every graph through ``graph_for_run`` (ADR-070): the published version when it has one, else the draft. The contract is
read the same way, here, by everything that needs it: the answer the pipeline editor reads (the mapping rows and the reference list of a
placement), the check before publishing, and the check at run time (the engine reads the frozen graph, which ``graph_for_run`` made). So while
an action is edited (its draft differs from its published version) the pipelines that use it keep showing, and keep being checked against, the
published contract; the new one appears when the action is published (or the old one again when the draft is discarded). An action that was
never published runs its draft (that is what ``graph_for_run`` does), so its draft contract is what the pipelines see then; ``running``
says which.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.graph.content import graph_of
from openartifact.graph.publishing import draft_changed, graph_for_run
from openartifact.graph.versions import current_version
from openartifact.models import Graph, GraphKind, NodeKind

#: Kinds of node that run another graph: what a placement is.
PLACEMENT_KINDS = (NodeKind.ACTION, NodeKind.PIPELINE)


def declared(graph: Mapping[str, Any] | None, kind: str, key: str) -> list[dict[str, Any]]:
    """The list a node of ``kind`` carries under ``key`` in its config (``inputs`` of the Trigger, ``outputs`` of the end), or ``[]``."""
    if graph is None:
        return []
    for node in graph["nodes"]:
        if node["kind"] == kind:
            value = (node.get("config") or {}).get(key)
            return [dict(f) for f in value] if isinstance(value, list) else []
    return []


def contract_in(graph: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The inputs and outputs a graph (as ``graph_for_run`` or ``graph_of`` returned it) declares."""
    ends = NodeKind.OUTPUT if graph.get("kind") == GraphKind.ACTION else NodeKind.COMPLETE
    return {
        "inputs": declared(graph, NodeKind.TRIGGER, "inputs"),
        "outputs": declared(graph, ends, "outputs"),
    }


async def contract_of(session: AsyncSession, graph_id: str) -> dict[str, Any] | None:
    """The contract of the version of ``graph_id`` that runs, or ``None`` when there is no such graph.

    ``version``: the published number, ``None`` while nothing is published; ``running``: ``"published"`` or ``"draft"`` (an action that was
    never published runs its draft); ``draft_changed``: the draft differs from the published version, so a newer contract waits for Publish.
    """
    graph = await session.get(Graph, graph_id)
    if graph is None:
        return None
    version = await current_version(session, graph)
    content = await graph_for_run(session, graph_id)
    return {
        "graph_id": graph.id,
        "kind": graph.kind,
        "version": version.number if version else None,
        "running": "published" if version else "draft",
        "draft_changed": await draft_changed(session, graph),
        **contract_in(content),
    }


async def placements_of(
    session: AsyncSession, graph_id: str
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Every graph that runs ``graph_id`` through a placement, as ``(graph name, [its placement nodes])``, by the version that runs."""
    out: list[tuple[str, list[dict[str, Any]]]] = []
    others = (await session.execute(select(Graph.id, Graph.name).where(Graph.id != graph_id))).all()
    for other_id, name in others:
        content = await graph_for_run(session, other_id)
        placed = [
            n
            for n in content["nodes"]
            if n["kind"] in PLACEMENT_KINDS and n.get("definition_id") == graph_id
        ]
        if placed:
            out.append((str(name), placed))
    return out


def _needs(spec: Mapping[str, Any]) -> bool:
    return bool(spec.get("required")) and not str(spec.get("default") or "").strip()


async def consumer_findings(session: AsyncSession, graph_id: str) -> list[dict[str, str]]:
    """What publishing the draft of ``graph_id`` would do to the graphs that run it (warnings; the owner decides): a placement that maps an
    input the new version no longer declares, a placement without a value for a new required input, and the outputs that disappear. Reads
    only. Nothing is reported while nothing is published (no graph can have used a contract yet) or while the contract does not change."""
    graph = await session.get(Graph, graph_id)
    if graph is None:
        return []
    version = await current_version(session, graph)
    if version is None:
        return []
    before = contract_in(json.loads(version.content))
    after = contract_in(await graph_of(session, graph_id))
    old_in = {s["name"] for s in before["inputs"]}
    new_in = {s["name"]: s for s in after["inputs"]}
    gone_out = sorted(
        {s["name"] for s in before["outputs"]} - {s["name"] for s in after["outputs"]}
    )
    found: list[dict[str, str]] = []
    for graph_name, placed in await placements_of(session, graph_id):
        for node in placed:
            mapped = (node.get("config") or {}).get("input_values") or {}
            shown = f"{graph_name}: {node.get('name') or graph.name}"
            for name in sorted(old_in - set(new_in)):
                if str(mapped.get(name) or "").strip():
                    found.append(
                        {
                            "code": "contract_input_removed",
                            "where": shown,
                            "message": f"{shown} gives a value to '{name}', which the new version no longer declares",
                        }
                    )
            for name, spec in new_in.items():
                if name not in old_in and _needs(spec) and not str(mapped.get(name) or "").strip():
                    found.append(
                        {
                            "code": "contract_input_new",
                            "where": shown,
                            "message": f"{shown} has no value for the new required input '{name}'",
                        }
                    )
        if gone_out:
            shown = f"{graph_name} ({len(placed)} place{'s' if len(placed) != 1 else ''})"
            found.append(
                {
                    "code": "contract_output_removed",
                    "where": shown,
                    "message": f"{shown} may read the output(s) {', '.join(gone_out)}, which the new version no longer declares",
                }
            )
    return found

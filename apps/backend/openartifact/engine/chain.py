"""The order of a pipeline and the way through it. Pure functions over plain node/edge dicts.

A node is ``{"id", "kind", "stage_id", "name", "label", "definition_id", "seconds", "x", "y"}``, an
edge ``{"source_id", "source_port", "target_id", "target_port"}`` (see :mod:`.snapshot`). Every
output has one edge, so the stages from trigger to complete form a chain.
"""

from __future__ import annotations

from typing import Any

Node = dict[str, Any]
Edge = dict[str, Any]


def edge_from(edges: list[Edge], node_id: str, port: str) -> Edge | None:
    """The edge leaving ``node_id`` at ``port``, if it is connected."""
    return next((e for e in edges if e["source_id"] == node_id and e["source_port"] == port), None)


def pipeline_chain(nodes: list[Node], edges: list[Edge]) -> list[dict[str, Any]]:
    """The entries the pipeline runs, in order: stages (with their actions) and pipeline nodes.

    Follows trigger → stage or pipeline node → ... and stops at a complete, an open end or a loop.
    Stages that are not on that path are not part of the pipeline. A pipeline node is an entry of
    kind ``pipeline`` named after the pipeline it calls (``pipeline_id``, ``None`` if none is set).
    """
    by_id = {n["id"]: n for n in nodes}
    trigger = next((n for n in nodes if n["kind"] == "trigger"), None)
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    link = edge_from(edges, trigger["id"], "out") if trigger else None
    while link is not None:
        node = by_id.get(link["target_id"])
        if node is None or node["kind"] not in ("stage", "pipeline") or node["id"] in seen:
            break
        seen.add(node["id"])
        if node["kind"] == "pipeline":
            chain.append(
                {
                    "id": node["id"],
                    "kind": "pipeline",
                    "name": node["label"],
                    "pipeline_id": node["definition_id"],
                    "first_action_id": None,
                    "actions": [],
                }
            )
            link = edge_from(edges, node["id"], "out")
            continue
        actions = sorted(
            (n for n in nodes if n["stage_id"] == node["id"] and n["kind"] == "action"),
            key=lambda n: (n["x"], n["y"]),
        )
        start = edge_from(edges, node["id"], "start")
        first = (
            start["target_id"]
            if start and by_id.get(start["target_id"], {}).get("stage_id") == node["id"]
            else (actions[0]["id"] if actions else None)
        )
        chain.append(
            {
                "id": node["id"],
                "kind": "stage",
                "name": node["name"],
                "first_action_id": first,
                "actions": [{"id": a["id"], "name": a["label"]} for a in actions],
            }
        )
        link = edge_from(edges, node["id"], "end")
    return chain

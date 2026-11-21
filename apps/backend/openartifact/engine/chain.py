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
    """The stages in the order the pipeline runs them, each with its actions.

    Follows trigger → stage → stage ... and stops at a complete, an open end or a loop. Stages that
    are not on that path are not part of the pipeline.
    """
    by_id = {n["id"]: n for n in nodes}
    trigger = next((n for n in nodes if n["kind"] == "trigger"), None)
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    link = edge_from(edges, trigger["id"], "out") if trigger else None
    while link is not None:
        stage = by_id.get(link["target_id"])
        if stage is None or stage["kind"] != "stage" or stage["id"] in seen:
            break
        seen.add(stage["id"])
        actions = sorted(
            (n for n in nodes if n["stage_id"] == stage["id"] and n["kind"] == "action"),
            key=lambda n: (n["x"], n["y"]),
        )
        start = edge_from(edges, stage["id"], "start")
        first = (
            start["target_id"]
            if start and by_id.get(start["target_id"], {}).get("stage_id") == stage["id"]
            else (actions[0]["id"] if actions else None)
        )
        chain.append(
            {
                "id": stage["id"],
                "name": stage["name"],
                "first_action_id": first,
                "actions": [{"id": a["id"], "name": a["label"]} for a in actions],
            }
        )
        link = edge_from(edges, stage["id"], "end")
    return chain

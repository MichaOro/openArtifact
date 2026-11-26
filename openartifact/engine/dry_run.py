"""What a dry run does with a node that writes (ADR-086).

A dry run runs under real conditions and executes nothing that changes something outside the run. A node whose effect is writing
(``graph/effects.py``) is not run: it is **skipped**, and its step says what it would have done ("Dry run: would have added this
comment: ..."). The step passes and carries ``data.dry_run = true`` and ``data.would_have``; it leaves no result of its own, so a later node
that needs one (the number of a comment it would have made) fails with a message that names the skipped node and says to use mock data
(``engine/context.py``).

What the node would have been given is worked out first: a reference that cannot be resolved, or an address that is not allowed, fails the
step the way the real run would, so the dry run does not hide a mistake behind the skip.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.chain import pipeline_chain
from openartifact.engine.context import ContextError, RunView, check_url_placement
from openartifact.engine.results import NodeResult, failed
from openartifact.graph.publishing import graph_for_run
from openartifact.models import Graph, GraphKind, NodeKind

SHOWN_CHARS = 300


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SHOWN_CHARS else text[: SHOWN_CHARS - 1] + "…"


def would_have(node: dict[str, Any], view: RunView) -> str:
    """What the node would have done, in words, with its inputs worked out (raises :class:`ContextError` like the real run)."""
    config = node.get("config") or {}
    kind = node.get("kind")
    if kind == NodeKind.ARTIFACT:
        text = view.render(str(config.get("text") or ""))
        return f"added this comment to the artifact: {_short(text)}"
    if kind == NodeKind.HTTP:
        method = str(config.get("method") or "GET")
        url = str(config.get("url") or "")
        check_url_placement(url)
        address = view.render(url, percent_encode=True)
        view.render(str(config.get("headers") or ""))
        body = view.render(str(config.get("body") or ""))
        sent = f" with a body of {len(body)} characters" if body else ""
        return f"sent {method} {_short(address)}{sent}"
    if kind == NodeKind.GITHUB:
        operation = str(config.get("operation") or "Get repository")
        repository = view.render(str(config.get("repository") or ""))
        comment = view.render(str(config.get("comment") or ""))
        number = view.render(str(config.get("number") or ""))
        where = f" on {repository}" if repository else ""
        target = f" #{number}" if number else ""
        said = f": {_short(comment)}" if comment.strip() else ""
        return f"run the GitHub operation '{operation}'{where}{target}{said}"
    if kind == NodeKind.POSTGRES:
        values = view.render(str(config.get("values") or ""))
        count = len([line for line in values.splitlines() if line.strip()])
        first = str(config.get("query") or "").strip().splitlines()[:1]
        statement = _short(first[0]) if first else "(no statement)"
        return f"run this statement with {count} parameter(s) that is allowed to change data: {statement}"
    if kind == NodeKind.CODE:
        code = str(config.get("code") or "")
        lines = len([line for line in code.splitlines() if line.strip()])
        return f"run the {config.get('language') or 'sh'} script of {lines} line(s)"
    return f"run the node '{node.get('name') or node.get('label') or kind}'"


async def placements_of_action(session: AsyncSession, definition_id: str) -> list[dict[str, str]]:
    """Where an action definition is placed in a pipeline (by the version that runs): ``{pipeline_id, pipeline_name, stage_id, stage_name,
    action_id}`` for each placement. A dry run of an action starts at one of them; an action in no pipeline has no way to run (ADR-086)."""
    found: list[dict[str, str]] = []
    pipelines = (
        await session.execute(
            select(Graph.id, Graph.name)
            .where(Graph.kind == GraphKind.PIPELINE)
            .order_by(Graph.name)
        )
    ).all()
    for pipeline_id, name in pipelines:
        content = await graph_for_run(session, pipeline_id)
        stages = {s["id"]: s for s in pipeline_chain(content["nodes"], content["edges"])}
        for node in content["nodes"]:
            stage = stages.get(node.get("stage_id") or "")
            if (
                node["kind"] == NodeKind.ACTION
                and node.get("definition_id") == definition_id
                and stage
            ):
                found.append(
                    {
                        "pipeline_id": pipeline_id,
                        "pipeline_name": str(name),
                        "stage_id": stage["id"],
                        "stage_name": str(stage.get("name") or ""),
                        "action_id": node["id"],
                    }
                )
    return found


async def skipped(node: dict[str, Any], limits: Any, view: RunView | None = None) -> NodeResult:
    """The result of a node a dry run does not run: a pass that says what it would have done, with no data of its own."""
    try:
        what = would_have(node, view or RunView())
    except ContextError as error:
        return failed(str(error))
    return NodeResult(
        "pass",
        reason=f"Dry run: would have {what}",
        data={"dry_run": True, "would_have": what},
    )

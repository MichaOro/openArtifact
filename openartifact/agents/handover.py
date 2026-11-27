"""The documents an agent hands over during one run of its node (ADR-080).

A Hand Over Tool checks what the model gives it against the schema of its fields (``graph/field_schema.py``). Every call goes through the
:class:`HandoverSink` of the node run: it counts the calls and keeps the last document that passed. When the node has ended, the engine
stores each document in the run context under the name of the tool node, as the result of that node, so a later node reads it with
``${(Name).data.field}``; the agent's own step shows them in its ``data`` (``handovers``) and every call stays in its tool calls.
"""

from __future__ import annotations

import json
from typing import Any

from openartifact.engine.results import NodeResult

HANDOVER_KIND = "handover_tool"


class HandoverSink:
    """The calls of the Hand Over Tools of one node run, by tool node."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._documents: dict[str, dict[str, Any]] = {}
        self._calls: dict[str, int] = {}
        self._order: list[str] = []

    def call(self, node: dict[str, Any], document: dict[str, Any] | None) -> None:
        """One call of the tool of ``node``; ``document`` is what passed the check, ``None`` for a call that was refused."""
        key = str(node["id"]) or str(node["name"])
        self._nodes[key] = node
        self._calls[key] = self._calls.get(key, 0) + 1
        if document is not None:
            self._documents[key] = document  # the last one that passed wins
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)

    def documents(self) -> dict[str, dict[str, Any]]:
        """The accepted documents by the name of their tool node, oldest first."""
        return {str(self._nodes[k]["name"]): self._documents[k] for k in self._order}

    def recorded(self) -> list[tuple[dict[str, Any], NodeResult]]:
        """What the engine stores in the run context: for every tool node with an accepted document, its result."""
        found: list[tuple[dict[str, Any], NodeResult]] = []
        for key in self._order:
            document = self._documents[key]
            found.append(
                (
                    self._nodes[key],
                    NodeResult(
                        "pass",
                        output=json.dumps(document, ensure_ascii=False),
                        data=dict(document),
                        attempts=self._calls[key],
                    ),
                )
            )
        return found

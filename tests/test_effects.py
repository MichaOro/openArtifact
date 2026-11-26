"""The effect declaration of the node kinds (ADR-086): what a dry run runs and what it skips.

Every kind says in its manifest what it does outside its run. A kind that says nothing would count as writing, so a new kind without
a declaration is a mistake this file catches; the table below is the agreed assignment.
"""

from __future__ import annotations

from typing import Any

import pytest

from openartifact.graph.effects import MIXED, NONE, READ, WRITE, effect_of, writes
from openartifact.graph.node_types import NODE_TYPES
from openartifact.models import NodeKind

#: The kinds whose effect is decided by the tools they offer: an Agent, an MCP server, the tools of an agent with Allow writes.
MIXED_KINDS = {NodeKind.AGENT, NodeKind.MCP_TOOL, NodeKind.GITHUB_TOOL, NodeKind.OPENARTIFACT_TOOL}


def test_every_kind_declares_what_it_does_outside_its_run() -> None:
    undeclared = sorted(k.value for k, t in NODE_TYPES.items() if t.effect is None)
    assert not undeclared, (
        f"declare `effect:` in the manifest of {', '.join(undeclared)} (a kind that says nothing counts as writing)"
    )


def test_a_declaration_names_settings_the_kind_has() -> None:
    for kind, node_type in NODE_TYPES.items():
        spec = node_type.effect or {}
        keys = {s.key for s in node_type.settings}
        for named in (spec.get("setting"), spec.get("flag")):
            assert named is None or named in keys, (
                f"{kind.value}: the effect names {named!r}, which is no setting"
            )
        if spec.get("setting"):
            options = next(s for s in node_type.settings if s.key == spec["setting"]).options or ()
            unknown = [
                v
                for v in spec.get("reading", [])
                if options and v not in options and v not in ("HEAD", "OPTIONS")
            ]
            assert not unknown, (
                f"{kind.value}: reading names values the setting does not offer: {unknown}"
            )


def test_only_an_agent_and_the_kinds_with_tools_of_their_own_are_mixed() -> None:
    for kind, node_type in NODE_TYPES.items():
        spec = node_type.effect or {}
        shown = {spec.get("default"), spec.get("flag_true")}
        if MIXED in shown:
            assert kind in MIXED_KINDS, f"{kind.value} says mixed but has no tools that decide"


@pytest.mark.parametrize(
    ("kind", "config", "expected"),
    [
        # what only works on the run's own context or on the structure: nothing outside
        (NodeKind.TRIGGER, {}, NONE),
        (NodeKind.OUTPUT, {}, NONE),
        (NodeKind.COMPLETE, {}, NONE),
        (NodeKind.TIMER, {}, NONE),
        (NodeKind.IF, {}, NONE),
        (NodeKind.SWITCH, {}, NONE),
        (NodeKind.SET, {}, NONE),
        (NodeKind.HANDOVER_TOOL, {}, NONE),
        # reads
        (NodeKind.CONTEXT, {}, READ),
        (NodeKind.SQLITE, {}, READ),
        (NodeKind.POSTGRES, {}, READ),
        (NodeKind.POSTGRES, {"allow_write": False}, READ),
        (NodeKind.HTTP, {"method": "GET"}, READ),
        (NodeKind.HTTP, {}, READ),  # the default method is GET
        (NodeKind.ARTIFACT, {"operation": "Get comments"}, READ),
        (NodeKind.GITHUB, {"operation": "Get issue"}, READ),
        (NodeKind.GITHUB, {"operation": "List pull requests"}, READ),
        (NodeKind.GITHUB, {}, READ),  # the default operation is Get repository
        (NodeKind.CODE, {"read_only": True}, READ),
        # writes
        (NodeKind.HTTP, {"method": "POST"}, WRITE),
        (NodeKind.HTTP, {"method": "PUT"}, WRITE),
        (NodeKind.HTTP, {"method": "PATCH"}, WRITE),
        (NodeKind.HTTP, {"method": "DELETE"}, WRITE),
        (NodeKind.ARTIFACT, {"operation": "Add comment"}, WRITE),
        (NodeKind.GITHUB, {"operation": "Create comment"}, WRITE),
        (NodeKind.GITHUB, {"operation": "Delete file"}, WRITE),
        (NodeKind.GITHUB, {"operation": "Invite user"}, WRITE),
        (NodeKind.POSTGRES, {"allow_write": True}, WRITE),
        (NodeKind.CODE, {}, WRITE),  # a script can do anything: writing unless marked read only
        (NodeKind.CODE, {"read_only": False}, WRITE),
        # decided by the tools
        (NodeKind.AGENT, {}, MIXED),
        (NodeKind.MCP_TOOL, {}, MIXED),
        (NodeKind.GITHUB_TOOL, {}, READ),
        (NodeKind.GITHUB_TOOL, {"allow_write": True}, MIXED),
        (NodeKind.OPENARTIFACT_TOOL, {}, READ),
        (NodeKind.OPENARTIFACT_TOOL, {"allow_write": True}, MIXED),
        (NodeKind.HTTP_TOOL, {"method": "POST"}, WRITE),
        (NodeKind.POSTGRES_TOOL, {"allow_write": True}, WRITE),
        (NodeKind.CODE_TOOL, {}, WRITE),
        (NodeKind.CODE_TOOL, {"read_only": True}, READ),
        (NodeKind.SQLITE_TOOL, {}, READ),
    ],
)
def test_the_agreed_assignment(kind: NodeKind, config: dict[str, Any], expected: str) -> None:
    assert effect_of(kind.value, config) == expected
    assert writes(kind.value, config) is (expected == WRITE)


def test_an_unknown_kind_and_an_unknown_value_count_as_writing() -> None:
    assert effect_of("no_such_kind", {}) == WRITE
    assert effect_of("http", {"method": "TRACE"}) == WRITE, (
        "a method the declaration does not know is a change"
    )
    assert effect_of("github", {"operation": "Something new"}) == WRITE
    assert effect_of("artifact", {"operation": "Something new"}) == WRITE

"""Every kind of node is complete where a forgotten step would only show late (docs/guides/extending.md, "Add a kind of node").

Icon, colour token, texts and effect are checked per kind elsewhere (tests/test_node_manifests.py, tests/test_i18n.py,
tests/test_effects.py). These two close the remaining gaps: the check constraint of the database is not seen by
``alembic check``, and the engine passes over a node whose kind has no executor as if it had passed
(``engine/runner.py``, the walk of a definition), so a forgotten registration would not fail a run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from openartifact.engine.executors import EXECUTORS
from openartifact.graph.node_types import NODE_TYPES
from openartifact.models import GraphKind, NodeKind

#: Kinds the engine handles itself where a definition starts and ends (the walk of a definition in ``engine/runner.py``).
_HANDLED_BY_THE_ENGINE = {NodeKind.TRIGGER, NodeKind.OUTPUT}


def test_the_migrated_database_accepts_a_node_of_every_kind(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("head")
    insert = "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES (?, 'g', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'action')")
        # the constraint is there and names the kinds
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_graph_nodes_kind"):
            conn.execute(insert, ("x", "no_such_kind", "X"))
        for kind in NodeKind:
            conn.execute(insert, (f"n-{kind.value}", kind.value, kind.value))
        stored = {row[0] for row in conn.execute("SELECT kind FROM graph_nodes")}
    assert stored == {k.value for k in NodeKind}


def test_every_kind_a_definition_runs_through_has_an_executor() -> None:
    """A kind on the path of an action definition (not a tool attached below an agent, not its start or end) needs an executor."""
    on_the_path = {
        kind
        for kind, node_type in NODE_TYPES.items()
        if GraphKind.ACTION in node_type.scopes
        and node_type.behaviour != "tool"
        and kind not in _HANDLED_BY_THE_ENGINE
    }
    assert on_the_path, "the manifests name no kind of an action definition"
    missing = sorted(k.value for k in on_the_path if k not in EXECUTORS)
    assert not missing, (
        f"kinds without an executor (register_executor in engine/executors.py): {missing}"
    )

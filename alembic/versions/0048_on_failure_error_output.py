"""If a node or an action fails: Stop, Continue, or Error output (ADR-061).

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-24

``on_failure`` (a key of a node's ``config``) had two values, ``fail`` and ``continue``, and the On Fail output of a
node and the On Error output of an action were always there. Now there are three values (``fail`` stops, ``continue``
goes on through On Pass, ``error_output`` goes on through the error output), and the error output is there only with the
third. Nothing may break:

* a node (Code, HTTP, GitHub, Postgres, Artifact, Agent, Edit Fields) or an action in a pipeline with a connection that
  leaves its error output gets ``error_output`` (it followed that connection before);
* one that is set to ``continue`` never used its error output, so a connection there (the editor hid nothing before) is
  dead and is removed;
* everything else keeps what it has (``fail`` is the default, the key stays as it is).

Only ``config`` JSON and ``graph_edges`` rows change: no table is rebuilt (see 0043). The downgrade takes ``error_output`` back
to the old default (the key is removed: ``fail`` followed the error output, and so did the old engine for every node), and
an action's setting goes with it.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The kinds that have the setting, with the port that is the error output of each.
ERROR_PORTS = {
    "code": "fail",
    "http": "fail",
    "github": "fail",
    "postgres": "fail",
    "artifact": "fail",
    "agent": "fail",
    "set": "fail",
    "action": "error",
}


def _config(raw: object) -> dict[str, object]:
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    return dict(raw) if isinstance(raw, dict) else {}


def upgrade() -> None:
    bind = op.get_bind()
    nodes = bind.execute(
        sa.text("SELECT id, kind, config FROM graph_nodes WHERE kind IN :kinds").bindparams(
            sa.bindparam("kinds", expanding=True)
        ),
        {"kinds": list(ERROR_PORTS)},
    ).fetchall()
    for node_id, kind, raw in nodes:
        config = _config(raw)
        used = bind.execute(
            sa.text(
                "SELECT id FROM graph_edges WHERE source_id = :id AND source_port = :port LIMIT 1"
            ),
            {"id": node_id, "port": ERROR_PORTS[kind]},
        ).scalar()
        if used is None:
            continue
        if config.get("on_failure") == "continue":
            # it never left by the error output: a connection there was dead
            bind.execute(sa.text("DELETE FROM graph_edges WHERE id = :id"), {"id": used})
            continue
        config["on_failure"] = "error_output"
        bind.execute(
            sa.text("UPDATE graph_nodes SET config = :config WHERE id = :id"),
            {"config": json.dumps(config), "id": node_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, kind, config FROM graph_nodes WHERE kind IN :kinds").bindparams(
            sa.bindparam("kinds", expanding=True)
        ),
        {"kinds": list(ERROR_PORTS)},
    ).fetchall()
    for node_id, kind, raw in rows:
        config = _config(raw)
        value = config.get("on_failure")
        # an action had no setting; a node's ``fail`` is the default and ``error_output`` is what ``fail`` did
        if value is None or (kind != "action" and value == "continue"):
            continue
        config.pop("on_failure")
        bind.execute(
            sa.text("UPDATE graph_nodes SET config = :config WHERE id = :id"),
            {"config": json.dumps(config), "id": node_id},
        )

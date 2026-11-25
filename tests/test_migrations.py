"""Tests for database migration management.

Tests cover Alembic initialization, fresh database setup,
sequential migration execution, and migration failure handling.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from alembic import command
from openartifact.config import Settings
from openartifact.database import build_engine, dispose_engine
from tests.helpers import alembic_config, bare_settings


async def test_fresh_database_connection(settings: Settings) -> None:
    """Fresh database connection succeeds without pre-existing files."""
    from sqlalchemy import text

    engine = build_engine(settings)
    assert engine is not None
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1


async def test_database_file_created(tmp_path: Path) -> None:
    """Database file is created on first connection."""
    from sqlalchemy import text

    settings = bare_settings(data_dir=tmp_path, database_filename="test.db")
    engine = build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    assert (tmp_path / "test.db").exists()


async def test_persistence_across_reconnect(settings: Settings) -> None:
    """Data persists across engine reconnection."""
    from sqlalchemy import text

    engine = build_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("CREATE TABLE persist_test (key TEXT)"))
        await conn.commit()

    # Dispose and reconnect
    await dispose_engine()
    engine2 = build_engine(settings)
    async with engine2.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='persist_test'")
        )
        rows = result.fetchall()
        assert any(r[0] == "persist_test" for r in rows)


def test_alembic_config_exists() -> None:
    """Alembic configuration file exists."""
    assert (Path(__file__).parent.parent / "alembic.ini").exists()


def test_alembic_script_exists() -> None:
    """Alembic migration scripts directory exists."""
    versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
    assert versions_dir.exists()
    scripts = list(versions_dir.glob("*.py"))
    assert len(scripts) > 0


def test_alembic_env_py_exists() -> None:
    """Alembic env.py exists."""
    env_path = Path(__file__).parent.parent / "alembic" / "env.py"
    assert env_path.exists()


def test_migration_0026_drops_and_restores_the_unused_tables(
    at_revision: Callable[[str], Path],
) -> None:
    """Down recreates projects and work_items as migration 0002 made them; up drops them again."""
    db = at_revision("0025")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Demo')")
        conn.execute("INSERT INTO work_items (id, project_id, title) VALUES ('w1', 'p1', 'T')")

    command.upgrade(alembic_config(), "0026")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"projects", "work_items"} & tables

    command.downgrade(alembic_config(), "0025")
    with sqlite3.connect(db) as conn:
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='work_items'"
            )
        }
        assert {
            "ix_work_items_project_id",
            "ix_work_items_status",
            "ix_work_items_project_status",
            "ix_work_items_project_status_position",
        } <= indexes
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Demo')")
        conn.execute("INSERT INTO work_items (id, project_id, title) VALUES ('w1', 'p1', 'T')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_work_items_status"
        ):  # ck_work_items_status
            conn.execute(
                "INSERT INTO work_items (id, project_id, title, status) VALUES ('w2','p1','T','DONE')"
            )
        with pytest.raises(
            sqlite3.IntegrityError, match=r"FOREIGN KEY constraint failed"
        ):  # fk_work_items_project_id
            conn.execute("INSERT INTO work_items (id, project_id, title) VALUES ('w3','nope','T')")
        conn.execute("DELETE FROM projects WHERE id = 'p1'")  # cascades
        assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0

    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"projects", "work_items"} & tables


def test_all_migrations_can_be_undone_and_applied_again(unmigrated_settings: Settings) -> None:
    """up, down to the first revision, up again: the same schema comes out both times."""
    db_path = unmigrated_settings.data_dir / unmigrated_settings.database_filename

    def schema() -> dict[str, Any]:
        """Columns, indexes and foreign keys per table (the DDL text may order clauses differently)."""
        with sqlite3.connect(db_path) as conn:
            tables = [
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            return {
                table: (
                    sorted(conn.execute(f"PRAGMA table_info({table})").fetchall()),
                    sorted(
                        (
                            name,
                            unique,
                            tuple(c[2] for c in conn.execute(f"PRAGMA index_info({name})")),
                        )
                        for _, name, unique, *_ in conn.execute(f"PRAGMA index_list({table})")
                    ),
                    sorted(
                        r[2:7] for r in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                    ),
                )
                for table in tables
            }

    command.upgrade(alembic_config(), "head")
    first = schema()
    command.downgrade(alembic_config(), "base")
    with sqlite3.connect(db_path) as conn:
        left = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert left <= {"alembic_version"}
    command.upgrade(alembic_config(), "head")
    assert schema() == first


def test_the_models_describe_exactly_what_the_migrations_create(
    migrated_settings: Settings,
) -> None:
    """``alembic check``: no table, column, index or constraint differs between models and migrations."""
    command.check(alembic_config())


def test_alembic_check_notices_a_difference(migrated_settings: Settings) -> None:
    """The check above is not vacuous: a missing index is reported."""
    from alembic.util import CommandError

    with sqlite3.connect(migrated_settings.data_dir / migrated_settings.database_filename) as conn:
        conn.execute("DROP INDEX ix_tasks_parent_id")
    with pytest.raises(CommandError, match="New upgrade operations detected"):
        command.check(alembic_config())


# ── one migration at a time: what each revision changes and that it can be undone ──


def test_migration_creates_tasks_table_and_enforces_status(migrated_settings: Settings) -> None:
    db_path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert cols == {
            "id",
            "number",
            "title",
            "body",
            "status",
            "position",
            "parent_id",
            "pipeline_id",
            "stage_id",
            "action_id",
            "archived_at",
            "archived_from_status",
            "created_by",
            "execution_seq",
            "field_values",
            "created_at",
            "updated_at",
        }
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO tasks (id, title, status) VALUES ('a', 'T', 'done')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"FOREIGN KEY constraint failed"
        ):  # the status must be a lane (foreign key since 0030)
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('b', 'T', 'BACKLOG')")


def test_migration_downgrade_removes_tasks(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0003")
    command.downgrade(alembic_config(), "0002")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tasks" not in tables
    assert "work_items" in tables


def test_migration_0004_backfills_positions_in_the_old_order(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0003")
    with sqlite3.connect(db) as conn:
        for tid, status, created in (
            ("t1", "backlog", "2026-01-01 10:00:00"),
            ("t2", "backlog", "2026-01-01 11:00:00"),
            ("t3", "backlog", "2026-01-01 12:00:00"),
            ("t4", "done", "2026-01-01 09:00:00"),
        ):
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
                (tid, tid, status, created),
            )
    command.upgrade(alembic_config(), "0004")
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, position FROM tasks ORDER BY status, position").fetchall()
    assert rows == [("t3", 0.0), ("t2", 1.0), ("t1", 2.0), ("t4", 0.0)]  # newest first, per lane
    command.downgrade(alembic_config(), "0003")
    with sqlite3.connect(db) as conn:
        assert "position" not in {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}


def test_migration_0005_adds_nullable_parent_id(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0004")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO tasks (id, title) VALUES ('old', 'existing row')")
    command.upgrade(alembic_config(), "0005")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT parent_id FROM tasks WHERE id='old'").fetchone() == (None,)
        # the CHECK constraint on status survives the schema change
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_tasks_status"
        ):
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('bad', 'x', 'BACKLOG')")
    command.downgrade(alembic_config(), "0004")
    with sqlite3.connect(db) as conn:
        assert "parent_id" not in {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert conn.execute("SELECT title FROM tasks WHERE id='old'").fetchone() == (
            "existing row",
        )


def test_migration_0006_numbers_existing_tasks_oldest_first(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0005")
    with sqlite3.connect(db) as conn:
        for tid, created in (("t2", "2026-01-02 10:00:00"), ("t1", "2026-01-01 10:00:00")):
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at) VALUES (?, ?, 'backlog', ?)",
                (tid, tid, created),
            )
    command.upgrade(alembic_config(), "0006")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, number FROM tasks ORDER BY number").fetchall() == [
            ("t1", 1),
            ("t2", 2),
        ]
        assert conn.execute("SELECT last FROM task_number_seq").fetchone() == (2,)


def test_migration_0007_clears_dangling_parents_and_keeps_the_rest(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0006")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO tasks (id, title, number) VALUES ('p', 'P', 1)")
        conn.execute("INSERT INTO tasks (id, title, number, parent_id) VALUES ('c', 'C', 2, 'p')")
        conn.execute(
            "INSERT INTO tasks (id, title, number, parent_id) VALUES ('o', 'O', 3, 'gone')"
        )
    command.upgrade(alembic_config(), "0007")
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, number, parent_id FROM tasks ORDER BY number").fetchall()
        assert rows == [("p", 1, None), ("c", 2, "p"), ("o", 3, None)]
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(tasks)")}
        assert {"ux_tasks_number", "ix_tasks_parent_id"} <= indexes
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_tasks_status"
        ):  # the status CHECK survived the rebuild
            conn.execute("INSERT INTO tasks (id, title, status) VALUES ('x', 'X', 'BACKLOG')")
    command.downgrade(alembic_config(), "0006")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO tasks (id, title, parent_id) VALUES ('z', 'Z', 'nowhere')"
        )  # no FK anymore


def test_artifacts_survive_every_later_migration(at_revision: Callable[[str], Path]) -> None:
    """Rows written at revision 0006 are still there, unchanged, at the newest revision."""
    db = at_revision("0006")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO tasks (id, title, number, status) VALUES ('p', 'P', 1, 'done')")
        conn.execute("INSERT INTO tasks (id, title, number, parent_id) VALUES ('c', 'C', 2, 'p')")
    command.upgrade(alembic_config(), "head")
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT id, title, number, status, parent_id, created_by, pipeline_id "
            "FROM tasks ORDER BY number"
        ).fetchall() == [
            ("p", "P", 1, "done", None, "user", None),
            ("c", "C", 2, "backlog", "p", "user", None),
        ]


def test_migration_0008_is_reversible(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0008")
    command.downgrade(alembic_config(), "0007")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"workflows", "workflow_nodes", "workflow_edges", "graphs"} & tables


def test_migration_0009_merges_the_inner_and_outer_stage_ports(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0008")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
        for node_id, kind, stage in (
            ("t", "trigger", None),
            ("s", "stage", None),
            ("a", "action", "s"),
            ("s2", "stage", None),
        ):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, stage_id, name) VALUES (?, 'w', ?, ?, ?)",
                (node_id, kind, stage, node_id),
            )
        for edge_id, src, sp, dst, dp in (
            ("e1", "t", "out", "s", "in"),
            ("e2", "s", "entry", "a", "in"),
            ("e3", "a", "pass", "s", "exit"),
            ("e4", "s", "out", "s2", "in"),
        ):
            conn.execute(
                "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
                "VALUES (?, 'w', ?, ?, ?, ?)",
                (edge_id, src, sp, dst, dp),
            )
    command.upgrade(alembic_config(), "0009")
    query = "SELECT id, source_port, target_port FROM workflow_edges ORDER BY id"
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [
            ("e1", "out", "start"),
            ("e2", "start", "in"),
            ("e3", "pass", "end"),
            ("e4", "end", "start"),
        ]
    command.downgrade(alembic_config(), "0008")
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [
            ("e1", "out", "in"),
            ("e2", "entry", "in"),
            ("e3", "pass", "exit"),
            ("e4", "out", "in"),
        ]


def test_migration_0010_adds_defaults_and_is_reversible(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0009")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
        for node_id, kind in (("t", "trigger"), ("s", "stage")):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES (?, 'w', ?, ?)",
                (node_id, kind, node_id),
            )
        conn.execute(
            "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
            "VALUES ('e', 'w', 't', 'out', 's', 'start')"
        )
    command.upgrade(alembic_config(), "0010")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT style, source_slot, target_slot FROM workflow_edges").fetchone()
    assert row == ("curved", 0, 0)
    command.downgrade(alembic_config(), "0009")
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(workflow_edges)")}
    assert not {"style", "source_slot", "target_slot"} & columns


def test_migration_0011_marks_existing_pipelines_and_is_reversible(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0010")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name) VALUES ('w', 'W')")
    command.upgrade(alembic_config(), "0011")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT kind FROM workflows").fetchall() == [("workflow",)]
        conn.execute("INSERT INTO workflows (id, name, kind) VALUES ('a', 'A', 'action')")
        conn.execute(
            "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES ('o', 'a', 'output', 'O')"
        )
    command.downgrade(alembic_config(), "0010")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM workflows").fetchall() == [("w",)]
        assert conn.execute("SELECT count(*) FROM workflow_nodes").fetchone() == (0,)


def test_migration_0012_adds_a_complete_and_connects_a_free_trigger(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0011")
    with sqlite3.connect(db) as conn:
        for pipeline in ("free", "busy"):
            conn.execute("INSERT INTO workflows (id, name) VALUES (?, ?)", (pipeline, pipeline))
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name, x) "
                "VALUES (?, ?, 'trigger', 'T', 60)",
                (f"t-{pipeline}", pipeline),
            )
        conn.execute(
            "INSERT INTO workflow_nodes (id, workflow_id, kind, name, x, width) "
            "VALUES ('s', 'busy', 'stage', 'S', 300, 360)"
        )
        conn.execute(
            "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
            "VALUES ('e', 'busy', 't-busy', 'out', 's', 'start')"
        )
    command.upgrade(alembic_config(), "0012")
    with sqlite3.connect(db) as conn:
        completes = dict(
            conn.execute("SELECT workflow_id, x FROM workflow_nodes WHERE kind = 'complete'")
        )
        edges = conn.execute(
            "SELECT workflow_id, source_id FROM workflow_edges ORDER BY 1"
        ).fetchall()
    assert completes == {"free": 60 + 160 + 96, "busy": 300 + 360 + 96}
    assert edges == [("busy", "t-busy"), ("free", "t-free")]
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT count(*) FROM workflow_edges WHERE workflow_id = 'busy'"
        ).fetchone() == (1,)  # the busy trigger keeps its own connection only


def test_migration_0013_is_reversible(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0013")
    with sqlite3.connect(db) as conn:
        assert "definition_id" in {r[1] for r in conn.execute("PRAGMA table_info(workflow_nodes)")}
    command.downgrade(alembic_config(), "0012")
    with sqlite3.connect(db) as conn:
        assert "definition_id" not in {
            r[1] for r in conn.execute("PRAGMA table_info(workflow_nodes)")
        }


def test_migration_0014_gives_existing_rows_unique_slugs(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0013")
    with sqlite3.connect(db) as conn:
        for row_id, name, kind in (
            ("a", "Test", "workflow"),
            ("b", "test", "workflow"),
            ("c", "Test", "action"),
        ):
            conn.execute(
                "INSERT INTO workflows (id, name, kind) VALUES (?, ?, ?)", (row_id, name, kind)
            )
    command.upgrade(alembic_config(), "0014")
    with sqlite3.connect(db) as conn:
        slugs = dict(conn.execute("SELECT id, slug FROM workflows"))
    assert slugs == {"a": "test", "b": "test-2", "c": "test"}
    command.downgrade(alembic_config(), "0013")
    with sqlite3.connect(db) as conn:
        assert "slug" not in {r[1] for r in conn.execute("PRAGMA table_info(workflows)")}


def test_migration_0015_points_output_edges_at_on_pass(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0014")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workflows (id, name, kind, slug) VALUES ('a', 'A', 'action', 'a')"
        )
        conn.execute(
            "INSERT INTO workflows (id, name, kind, slug) VALUES ('w', 'W', 'workflow', 'w')"
        )
        for node_id, pipeline, kind in (
            ("t", "a", "trigger"),
            ("o", "a", "output"),
            ("tw", "w", "trigger"),
            ("c", "w", "complete"),
        ):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES (?, ?, ?, ?)",
                (node_id, pipeline, kind, node_id),
            )
        for edge_id, pipeline, src, dst in (("e1", "a", "t", "o"), ("e2", "w", "tw", "c")):
            conn.execute(
                "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, "
                "target_port) VALUES (?, ?, ?, 'out', ?, 'in')",
                (edge_id, pipeline, src, dst),
            )
    command.upgrade(alembic_config(), "0015")
    query = "SELECT id, target_port FROM workflow_edges ORDER BY id"
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [("e1", "pass"), ("e2", "in")]
    command.downgrade(alembic_config(), "0014")
    with sqlite3.connect(db) as conn:
        assert conn.execute(query).fetchall() == [("e1", "in"), ("e2", "in")]


def test_migration_0016_is_reversible(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0016")
    with sqlite3.connect(db) as conn:
        assert "seconds" in {r[1] for r in conn.execute("PRAGMA table_info(workflow_nodes)")}
    command.downgrade(alembic_config(), "0015")
    with sqlite3.connect(db) as conn:
        assert "seconds" not in {r[1] for r in conn.execute("PRAGMA table_info(workflow_nodes)")}


def _seed_old_names(db: Any) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workflows (id, name, kind, slug) VALUES ('p', 'P', 'workflow', 'p')"
        )
        conn.execute(
            "INSERT INTO workflows (id, name, kind, slug) VALUES ('d', 'D', 'action', 'd')"
        )
        for node_id, graph, kind, definition in (
            ("pt", "p", "trigger", None),
            ("pc", "p", "complete", None),
            ("pn", "p", "pipeline", "p"),
            ("dt", "d", "trigger", None),
            ("do", "d", "output", None),
        ):
            conn.execute(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name, definition_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (node_id, graph, kind, node_id, definition),
            )
        conn.execute(
            "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, target_port) "
            "VALUES ('pe', 'p', 'pt', 'out', 'pc', 'in')"
        )
        conn.execute("INSERT INTO tasks (id, title, pipeline_id) VALUES ('t', 'T', 'p')")
        conn.execute(
            "INSERT INTO pipeline_runs (id, task_id, workflow_id, status, started_by, snapshot) "
            "VALUES ('r', 't', 'p', 'done', 'user', '{\"workflow_id\": \"p\"}')"
        )


def test_migration_0020_renames_workflows_to_graphs_and_keeps_the_data(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0019")
    _seed_old_names(db)
    command.upgrade(alembic_config(), "0020")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"graphs", "graph_nodes", "graph_edges"} <= tables
        assert not {"workflows", "workflow_nodes", "workflow_edges"} & tables
        assert conn.execute("SELECT id, kind, slug FROM graphs ORDER BY id").fetchall() == [
            ("d", "action", "d"),
            ("p", "pipeline", "p"),
        ]
        assert conn.execute("SELECT count(*) FROM graph_nodes").fetchone() == (5,)
        assert conn.execute(
            "SELECT graph_id, definition_id FROM graph_nodes WHERE id = 'pn'"
        ).fetchone() == ("p", "p")
        assert conn.execute(
            "SELECT graph_id, source_id, target_id FROM graph_edges"
        ).fetchall() == [("p", "pt", "pc")]
        assert conn.execute("SELECT pipeline_id, snapshot FROM pipeline_runs").fetchone() == (
            "p",
            '{"workflow_id": "p"}',  # stored snapshots are left alone
        )
        assert conn.execute("SELECT pipeline_id FROM tasks").fetchone() == ("p",)
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        # the foreign keys still point at the renamed tables
        conn.execute("DELETE FROM graphs WHERE id = 'p'")
        assert conn.execute("SELECT count(*) FROM graph_nodes WHERE graph_id = 'p'").fetchone() == (
            0,
        )
        assert conn.execute("SELECT count(*) FROM graph_edges").fetchone() == (0,)
        assert conn.execute("SELECT pipeline_id FROM tasks").fetchone() == (None,)
        assert conn.execute("SELECT pipeline_id FROM pipeline_runs").fetchone() == (None,)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(graph_nodes)")}
        assert {"graph_id", "definition_id"} <= columns
        assert "workflow_id" not in columns


def test_migration_0020_allows_only_pipeline_and_action_kinds(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0019")
    command.upgrade(alembic_config(), "0020")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, kind, slug) VALUES ('a', 'A', 'pipeline', 'a')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"CHECK constraint failed: ck_graphs_kind"
        ):
            conn.execute(
                "INSERT INTO graphs (id, name, kind, slug) VALUES ('b', 'B', 'workflow', 'b')"
            )


def test_migration_0020_is_reversible(at_revision: Callable[[str], Path]) -> None:
    db = at_revision("0019")
    _seed_old_names(db)
    command.upgrade(alembic_config(), "0020")
    command.downgrade(alembic_config(), "0019")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"workflows", "workflow_nodes", "workflow_edges"} <= tables
        assert not {"graphs", "graph_nodes", "graph_edges"} & tables
        assert conn.execute("SELECT id, kind FROM workflows ORDER BY id").fetchall() == [
            ("d", "action"),
            ("p", "workflow"),
        ]
        assert conn.execute("SELECT count(*) FROM workflow_nodes").fetchone() == (5,)
        assert conn.execute("SELECT workflow_id FROM workflow_edges").fetchall() == [("p",)]
        assert conn.execute("SELECT workflow_id FROM pipeline_runs").fetchall() == [("p",)]
        assert conn.execute(
            "SELECT definition_id FROM workflow_nodes WHERE id = 'pn'"
        ).fetchone() == ("p",)
    command.upgrade(alembic_config(), "head")


def test_migration_0017_adds_pipeline_runs_with_their_constraints(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0016")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO tasks (id, title, number) VALUES ('t', 'T', 1)")
        conn.execute("INSERT INTO workflows (id, name, slug) VALUES ('w', 'W', 'w')")
    command.upgrade(alembic_config(), "0017")
    run = "INSERT INTO pipeline_runs (id, task_id, workflow_id, status, started_by, snapshot) "
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(run + "VALUES ('r', 't', 'w', 'running', 'user', '{}')")
        conn.execute(
            "INSERT INTO run_stages (run_id, stage_id, name, position, status) "
            "VALUES ('r', 's1', 'Build', 0, 'pending')"
        )
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_pipeline_runs_status"):
            conn.execute(run + "VALUES ('x', 't', 'w', 'paused', 'user', '{}')")
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_pipeline_runs_started_by"):
            conn.execute(run + "VALUES ('x', 't', 'w', 'running', 'robot', '{}')")
        with pytest.raises(
            sqlite3.IntegrityError, match=r"UNIQUE constraint failed: pipeline_runs\.task_id"
        ):  # one run per artifact
            conn.execute(run + "VALUES ('x', 't', 'w', 'done', 'user', '{}')")
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_run_stages_status"):
            conn.execute(
                "INSERT INTO run_stages (run_id, stage_id, name, position, status) "
                "VALUES ('r', 's2', 'Test', 1, 'maybe')"
            )
        conn.execute("DELETE FROM workflows WHERE id = 'w'")  # the run outlives its pipeline
        assert conn.execute("SELECT workflow_id FROM pipeline_runs").fetchall() == [(None,)]
        conn.execute("DELETE FROM tasks WHERE id = 't'")  # but not its artifact
        assert conn.execute("SELECT count(*) FROM pipeline_runs").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM run_stages").fetchone() == (0,)

    command.downgrade(alembic_config(), "0016")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"pipeline_runs", "run_stages"} & tables


def test_migration_0018_allows_pipeline_nodes_and_downgrade_removes_them_with_their_edges(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0017")
    node = "INSERT INTO workflow_nodes (id, workflow_id, kind, name) VALUES (?, 'w', ?, ?)"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO workflows (id, name, slug) VALUES ('w', 'W', 'w')")
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_workflow_nodes_kind"):
            conn.execute(node, ("p", "pipeline", "P"))
    command.upgrade(alembic_config(), "0018")
    with sqlite3.connect(db) as conn:
        for node_id, kind in (("t", "trigger"), ("p", "pipeline"), ("s", "stage")):
            conn.execute(node, (node_id, kind, node_id))
        for edge_id, source, port, target in (
            ("e1", "t", "out", "p"),
            ("e2", "p", "pass", "s"),
            ("e3", "t", "other", "s"),
        ):
            conn.execute(
                "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, target_id, "
                "target_port) VALUES (?, 'w', ?, ?, ?, 'start')",
                (edge_id, source, port, target),
            )

    command.downgrade(alembic_config(), "0017")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM workflow_nodes ORDER BY id").fetchall() == [
            ("s",),
            ("t",),
        ]
        assert conn.execute("SELECT id FROM workflow_edges").fetchall() == [("e3",)]
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_workflow_nodes_kind"):
            conn.execute(node, ("p2", "pipeline", "P"))


def test_migration_0019_adds_the_target_and_origin_columns_and_keeps_the_artifacts(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0018")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO tasks (id, title, number) VALUES ('old', 'Old', 1)")
        conn.execute("INSERT INTO workflows (id, name, slug) VALUES ('w', 'W', 'w')")
    command.upgrade(alembic_config(), "0019")
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute(
            "SELECT title, pipeline_id, stage_id, action_id, created_by FROM tasks"
        ).fetchall() == [("Old", None, None, None, "user")]
        conn.execute(
            "INSERT INTO tasks (id, title, number, pipeline_id, stage_id, action_id, created_by) "
            "VALUES ('new', 'New', 2, 'w', 's', 'a', 'mcp')"
        )
        with pytest.raises(sqlite3.IntegrityError, match=r"ck_tasks_created_by"):
            conn.execute(
                "INSERT INTO tasks (id, title, number, created_by) VALUES ('x', 'X', 3, 'bot')"
            )
        conn.execute("DELETE FROM workflows WHERE id = 'w'")  # the artifact keeps living
        assert conn.execute("SELECT pipeline_id FROM tasks WHERE id = 'new'").fetchone() == (None,)

    command.downgrade(alembic_config(), "0018")
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert not {"pipeline_id", "stage_id", "action_id", "created_by"} & columns
        assert conn.execute("SELECT id, title, number FROM tasks ORDER BY number").fetchall() == [
            ("old", "Old", 1),
            ("new", "New", 2),
        ]


def test_migration_0043_drops_the_history_policy_and_downgrade_brings_the_columns_back_empty(
    at_revision: Callable[[str], Path],
) -> None:
    db = at_revision("0042")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, number, history_keep_last, history_keep_hours) "
            "VALUES ('t1', 'Keep me', 'backlog', 1, 5, 24)"
        )
        before = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(tasks)")}
    assert {"history_keep_last", "history_keep_hours"} <= before
    command.upgrade(alembic_config(), "0043")
    with sqlite3.connect(db) as conn:
        after = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert after == before - {"history_keep_last", "history_keep_hours"}
        assert conn.execute("SELECT title, number FROM tasks").fetchall() == [("Keep me", 1)]
        assert {
            r[1] for r in conn.execute("PRAGMA index_list(tasks)")
        } == indexes  # the table was not rebuilt
        lane_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='credentials'"
        ).fetchone()[0]
        assert "NOCASE" in lane_sql  # the collations of other tables are untouched
    command.downgrade(alembic_config(), "0042")
    with sqlite3.connect(db) as conn:
        assert {r[1] for r in conn.execute("PRAGMA table_info(tasks)")} == before
        assert conn.execute(
            "SELECT history_keep_last, history_keep_hours FROM tasks"
        ).fetchall() == [(None, None)]


def test_migration_0048_gives_a_used_error_output_its_setting_and_keeps_the_rest(
    at_revision: Callable[[str], Path],
) -> None:
    """A node or action whose error output is connected gets ``error_output`` (it followed that connection before); a
    node set to ``continue`` never used the output, so a connection there is dead and goes; the others keep their value."""
    import json

    db = at_revision("0047")
    nodes = [
        # id, kind, config, error port, has an edge there
        ("n_edge", "code", {"code": "x"}, "fail", True),
        ("n_fail_edge", "http", {"on_failure": "fail"}, "fail", True),
        ("n_continue_edge", "code", {"on_failure": "continue"}, "fail", True),
        ("n_plain", "code", {"code": "y"}, "fail", False),
        ("n_fail", "code", {"on_failure": "fail"}, "fail", False),
        ("n_continue", "http", {"on_failure": "continue"}, "fail", False),
        ("a_edge", "action", {}, "error", True),
        ("a_plain", "action", {}, "error", False),
    ]
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('g', 'G', 'g', 'pipeline')")
        conn.execute(
            "INSERT INTO graph_nodes (id, graph_id, kind, name) VALUES ('end', 'g', 'complete', 'End')"
        )
        for node_id, kind, config, port, edge in nodes:
            conn.execute(
                "INSERT INTO graph_nodes (id, graph_id, kind, name, config) VALUES (?, 'g', ?, ?, ?)",
                (node_id, kind, node_id, json.dumps(config)),
            )
            if edge:
                conn.execute(
                    "INSERT INTO graph_edges (id, graph_id, source_id, source_port, target_id, target_port) "
                    "VALUES (?, 'g', ?, ?, 'end', 'in')",
                    (f"e_{node_id}", node_id, port),
                )
        # an edge of another port is not touched
        conn.execute(
            "INSERT INTO graph_edges (id, graph_id, source_id, source_port, target_id, target_port) "
            "VALUES ('e_pass', 'g', 'n_plain', 'pass', 'end', 'in')"
        )

    command.upgrade(alembic_config(), "0048")
    with sqlite3.connect(db) as conn:
        config = {
            r[0]: json.loads(r[1]) for r in conn.execute("SELECT id, config FROM graph_nodes")
        }
        edges = {r[0] for r in conn.execute("SELECT id FROM graph_edges")}
    assert config["n_edge"] == {"code": "x", "on_failure": "error_output"}
    assert config["n_fail_edge"] == {"on_failure": "error_output"}
    assert config["a_edge"] == {"on_failure": "error_output"}
    assert config["n_continue_edge"] == {
        "on_failure": "continue"
    }  # stays, its dead connection goes
    assert "e_n_continue_edge" not in edges
    assert config["n_plain"] == {"code": "y"}  # nothing was connected: the default (stop) stays
    assert config["n_fail"] == {"on_failure": "fail"}
    assert config["n_continue"] == {"on_failure": "continue"}
    assert config["a_plain"] == {}
    assert {"e_n_edge", "e_n_fail_edge", "e_a_edge", "e_pass"} <= edges  # the live connections stay

    command.downgrade(alembic_config(), "0047")
    with sqlite3.connect(db) as conn:
        config = {
            r[0]: json.loads(r[1]) for r in conn.execute("SELECT id, config FROM graph_nodes")
        }
    assert config["n_edge"] == {"code": "x"}  # the old default followed the error output
    assert config["n_fail_edge"] == {}
    assert config["a_edge"] == {}  # an action had no such setting before
    assert config["n_continue_edge"] == {"on_failure": "continue"}
    assert config["n_continue"] == {"on_failure": "continue"}


def test_migration_0050_brings_an_action_definition_and_its_uses_in_step(
    at_revision: Callable[[str], Path],
) -> None:
    """A use in the error output mode switches its definition's On Fail on; every use that stops the run follows a
    definition that has On Fail; a use set to continue is left alone; definitions without any of it change nothing."""
    import json

    db = at_revision("0049")
    # definition -> (has On Fail before); uses -> (definition, config)
    definitions = {"d_on": 1, "d_off": 0, "d_wanted": 0, "d_plain": 0}
    uses = [
        ("u_on_stop", "d_on", {}),  # offered, stops: gets the error output
        ("u_on_fail", "d_on", {"on_failure": "fail"}),
        ("u_on_continue", "d_on", {"on_failure": "continue"}),  # untouched
        ("u_on_error", "d_on", {"on_failure": "error_output"}),
        ("u_wants", "d_wanted", {"on_failure": "error_output"}),  # switches d_wanted on ...
        ("u_wanted_stop", "d_wanted", {}),  # ... and carries its other use along
        ("u_plain", "d_plain", {}),  # a definition without it: nothing changes
        ("u_off_continue", "d_off", {"on_failure": "continue"}),
        ("u_shell", None, {}),  # an empty action has no definition
    ]
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO graphs (id, name, slug, kind) VALUES ('p', 'P', 'p', 'pipeline')")
        for name, flag in definitions.items():
            conn.execute(
                "INSERT INTO graphs (id, name, slug, kind) VALUES (?, ?, ?, 'action')",
                (name, name, name),
            )
            conn.execute(
                "INSERT INTO graph_nodes (id, graph_id, kind, name, fail_enabled) VALUES (?, ?, 'output', 'Output', ?)",
                (f"out_{name}", name, flag),
            )
        for use_id, definition, config in uses:
            conn.execute(
                "INSERT INTO graph_nodes (id, graph_id, kind, name, definition_id, config) "
                "VALUES (?, 'p', 'action', ?, ?, ?)",
                (use_id, use_id, definition, json.dumps(config)),
            )

    command.upgrade(alembic_config(), "0050")
    with sqlite3.connect(db) as conn:
        flags = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT graph_id, fail_enabled FROM graph_nodes WHERE kind = 'output'"
            )
        }
        config = {
            r[0]: json.loads(r[1])
            for r in conn.execute("SELECT id, config FROM graph_nodes WHERE kind = 'action'")
        }
    assert flags == {"d_on": 1, "d_off": 0, "d_wanted": 1, "d_plain": 0}
    assert config["u_on_stop"] == {"on_failure": "error_output"}
    assert config["u_on_fail"] == {"on_failure": "error_output"}
    assert config["u_on_continue"] == {"on_failure": "continue"}
    assert config["u_on_error"] == {"on_failure": "error_output"}
    assert config["u_wants"] == {"on_failure": "error_output"}
    assert config["u_wanted_stop"] == {"on_failure": "error_output"}
    assert config["u_plain"] == {}
    assert config["u_off_continue"] == {"on_failure": "continue"}
    assert config["u_shell"] == {}

    command.downgrade(alembic_config(), "0049")  # nothing to undo: both states were legal before
    with sqlite3.connect(db) as conn:
        again = {
            r[0]: json.loads(r[1])
            for r in conn.execute("SELECT id, config FROM graph_nodes WHERE kind = 'action'")
        }
    assert again == config

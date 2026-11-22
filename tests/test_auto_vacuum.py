"""The database file gives freed space back: ``auto_vacuum = FULL`` for new and converted databases."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from alembic import command
from openartifact.config import Settings
from openartifact.database import ensure_auto_vacuum
from tests.helpers import alembic_config

FULL = 1


def _mode(path: Path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])


def _fill(path: Path, rows: int = 400, size: int = 8192) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS blobs (id INTEGER PRIMARY KEY, data BLOB)")
        conn.executemany(
            "INSERT INTO blobs (data) VALUES (?)", [(b"x" * size,) for _ in range(rows)]
        )


def test_a_new_database_is_created_in_full_auto_vacuum_mode(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    assert ensure_auto_vacuum(path) == "created"
    assert _mode(path) == FULL
    _fill(path)  # the mode survives the first real tables
    assert _mode(path) == FULL


def test_an_existing_database_is_converted_once_and_keeps_its_data(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _fill(path, rows=50)
    assert _mode(path) == 0
    assert ensure_auto_vacuum(path) == "converted"
    assert _mode(path) == FULL
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM blobs").fetchone() == (50,)
    assert ensure_auto_vacuum(path) == "unchanged"


def test_deleting_rows_shrinks_the_file(tmp_path: Path) -> None:
    path = tmp_path / "grow.db"
    ensure_auto_vacuum(path)
    _fill(path)
    full = path.stat().st_size
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("DELETE FROM blobs")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert path.stat().st_size < full / 10, "the freed pages stayed in the file"


def test_the_migrations_create_the_database_in_full_mode(unmigrated_settings: Settings) -> None:
    command.upgrade(alembic_config(), "head")
    assert _mode(unmigrated_settings.data_dir / unmigrated_settings.database_filename) == FULL


def test_the_migrations_convert_a_database_that_already_exists(
    unmigrated_settings: Settings,
) -> None:
    path = unmigrated_settings.data_dir / unmigrated_settings.database_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:  # a database from before the change
        conn.execute("CREATE TABLE keep (x)")
        conn.execute("INSERT INTO keep VALUES (1)")
    assert _mode(path) == 0
    command.upgrade(alembic_config(), "head")
    assert _mode(path) == FULL
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT x FROM keep").fetchone() == (1,)

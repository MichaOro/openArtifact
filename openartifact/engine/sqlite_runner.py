"""Runs one read-only SQL statement on a SQLite database of the application for the SQLite node and the SQLite Tool (ADR-068).

The node is for guard actions (a guard that judges the health of a run, or any action that needs to read data of the
application). It never writes, and what it may read is decided by SQLite itself, not by looking at the text of the statement:

* the file is opened read-only (``mode=ro``) and ``query_only`` is on, so a change is refused by the engine;
* an **authorizer** answers every step the engine takes while it prepares the statement: a ``SELECT`` is fine; ``INSERT``,
  ``UPDATE``, ``DELETE``, ``CREATE``, ``DROP``, ``ATTACH``, ``PRAGMA``, a transaction, ... are refused; ``load_extension`` and the
  like are refused as functions;
* a table is read **only through the views a data source lists** (``v_guard_*`` for the application's own database: a stable,
  documented interface without sensitive columns). A statement that names a table directly is refused, and so is a view that is
  not listed;
* on top of that sits a fixed **floor** that no setting can lift: tables whose name says secret, credential, token, provider or
  setting, and columns that hold a password, a key or a hash, can never be read, not even through a view. The author may block
  more (``table`` or ``table.column``), never fewer;
* one statement only, values travel as parameters (``?1``, ``?2``, ...), a time limit (the engine is interrupted), a row limit and a
  byte limit.

Data sources are registered by name (:func:`register`); there is no way to name a file in a node. The application registers its own
(``app``); an extension registers more, each with its own list of readable views and its own denials.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from openartifact.engine.context import ContextError, RunView
from openartifact.engine.postgres_runner import QueryResult
from openartifact.engine.results import NodeResult, failed

#: What the node keeps of a result (the run context holds 64 KiB in all).
RESULT_LIMIT_BYTES = 48 * 1024
#: The floor: tables and columns that are never readable, whatever a data source or a node says.
FLOOR_TABLE = re.compile(r"secret|credential|token|provider|setting|password", re.IGNORECASE)
FLOOR_COLUMN = re.compile(
    r"password|secret|api_?key|private_?key|token_hash|_hash$|^hash$", re.IGNORECASE
)
#: Functions of the engine that reach outside the statement.
DENIED_FUNCTIONS = frozenset({"load_extension", "fts3_tokenizer", "readfile", "writefile", "edit"})
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
APP_SOURCE = "app"


class SqliteError(Exception):
    """The statement could not be run; the message is safe to show."""


@dataclass(frozen=True)
class DataSource:
    """A SQLite database a node may read: where it is, and which views (or tables) a statement may read directly. What a view reads
    inside is allowed, except the floor and what ``denied`` names (``table`` or ``table.column``)."""

    name: str
    label: str
    path: Path
    readable: frozenset[str]
    denied: frozenset[str] = field(default_factory=frozenset)


def application_source(path: Path) -> DataSource:
    """The application's own database, read through the ``v_guard_*`` views (``engine/guard_views.py``)."""
    from openartifact.engine.guard_views import VIEWS

    return DataSource(APP_SOURCE, "Application data", path, frozenset(VIEWS))


def blocked_names(text: str) -> frozenset[str]:
    """The names a node blocks, one per line: ``table`` or ``table.column`` (lowercase, as SQLite compares them)."""
    names: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry:
            continue
        table, dot, column = entry.partition(".")
        if not _NAME.fullmatch(table) or (dot and not _NAME.fullmatch(column)):
            raise SqliteError(f"Line {number} of the blocked list is not 'table' or 'table.column'")
        names.add(entry.lower())
    return frozenset(names)


def _is_denied(table: str, column: str | None, source: DataSource, blocked: frozenset[str]) -> bool:
    low_table, low_column = table.lower(), (column or "").lower()
    if FLOOR_TABLE.search(low_table) or (low_column and FLOOR_COLUMN.search(low_column)):
        return True
    denied = {name.lower() for name in source.denied} | blocked
    return low_table in denied or bool(low_column and f"{low_table}.{low_column}" in denied)


#: Table-valued functions that only read the text they are given.
TABLE_FUNCTIONS = frozenset({"json_each", "json_tree"})


def _recorder(view: str, seen: set[tuple[str, str]]) -> Callable[..., int]:
    def record(
        action: int, arg1: str | None, arg2: str | None, _db: str | None, inner: str | None
    ) -> int:
        if action == sqlite3.SQLITE_READ and arg1 and (inner or "").lower() == view.lower():
            seen.add((arg1.lower(), (arg2 or "").lower()))
        return sqlite3.SQLITE_OK

    return record


def view_reads(
    conn: sqlite3.Connection, readable: frozenset[str]
) -> dict[str, frozenset[tuple[str, str]]]:
    """What each listed view reads inside, as ``(table, column)`` pairs: found by preparing ``SELECT * FROM <view>`` once with a
    recording authorizer, so it follows the definition of the view in this very database. (A statement that defines a name like a
    listed view of its own, in a ``WITH``, can then read no more than that view reads.)"""
    found: dict[str, frozenset[tuple[str, str]]] = {}
    for view in sorted(readable):
        seen: set[tuple[str, str]] = set()
        conn.set_authorizer(_recorder(view, seen))
        try:
            conn.execute(f'EXPLAIN SELECT * FROM "{view}"').fetchall()
        except sqlite3.Error:
            seen = set()  # a listed view that is not there reads nothing
        found[view.lower()] = frozenset(seen)
    conn.set_authorizer(None)
    return found


def make_authorizer(
    source: DataSource,
    blocked: frozenset[str],
    refused: list[str],
    reads: Mapping[str, frozenset[tuple[str, str]]],
) -> Callable[..., int]:
    """The authorizer of one statement; what it refuses is noted in ``refused`` (names only) for the message. ``reads`` is what each
    listed view reads inside (:func:`view_reads`).

    A count (``count(*)``, ``EXISTS``) reads a table with no column: that is allowed for a table that is not denied, since it shows
    how many rows there are, never what is in them."""
    readable = {name.lower() for name in source.readable}

    def authorize(
        action: int, arg1: str | None, arg2: str | None, db: str | None, inner: str | None
    ) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or "").lower() in DENIED_FUNCTIONS:
                refused.append(f"the function {arg2}")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and arg1:
            if db not in (None, "main"):
                refused.append(arg1)
                return sqlite3.SQLITE_DENY
            if _is_denied(arg1, arg2, source, blocked):
                refused.append(f"{arg1}.{arg2}" if arg2 and FLOOR_COLUMN.search(arg2) else arg1)
                return sqlite3.SQLITE_DENY
            table, column = arg1.lower(), (arg2 or "").lower()
            if not column:
                return sqlite3.SQLITE_OK  # a count: how many rows, not what is in them
            if table in readable or table in TABLE_FUNCTIONS:
                return sqlite3.SQLITE_OK  # a listed view itself
            if inner and (table, column) in reads.get(inner.lower(), frozenset()):
                return (
                    sqlite3.SQLITE_OK
                )  # what a listed view reads inside, and no more than its definition says
            refused.append(arg1)
            return sqlite3.SQLITE_DENY
        refused.append("a change or another kind of statement")
        return sqlite3.SQLITE_DENY

    return authorize


def _cell(value: Any) -> Any:
    return f"<{len(value)} bytes>" if isinstance(value, bytes) else value


def _unique(names: Sequence[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name}_{count}")
    return out


def query(
    source: DataSource,
    sql: str,
    values: Sequence[str] = (),
    *,
    blocked: frozenset[str] = frozenset(),
    timeout: float = 30.0,
    max_rows: int = 100,
    max_bytes: int = RESULT_LIMIT_BYTES,
) -> QueryResult:
    """One read-only statement on ``source`` (blocking: run it in a thread). :class:`SqliteError` with a safe message otherwise."""
    if not sql.strip():
        raise SqliteError("The query is empty")
    uri = f"file:{quote(str(source.path))}?mode=ro"
    refused: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        conn = sqlite3.connect(
            uri, uri=True, timeout=min(timeout, 5.0), check_same_thread=False, isolation_level=None
        )
    except sqlite3.Error:
        raise SqliteError(f"The data source '{source.name}' cannot be opened") from None
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        conn.set_authorizer(
            make_authorizer(source, blocked, refused, view_reads(conn, source.readable))
        )
        try:
            cursor = conn.execute(sql, tuple(values))
            names = _unique([d[0] for d in cursor.description or []])
            result = QueryResult(columns=names)
            size = 2
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                item = {name: _cell(cell) for name, cell in zip(names, row, strict=True)}
                cost = len(json.dumps(item, ensure_ascii=False, default=str)) + 2
                if len(result.rows) >= max_rows or size + cost > max_bytes:
                    result.truncated = True
                    break
                size += cost
                result.rows.append(item)
            result.row_count = len(result.rows)
            return result
        except sqlite3.ProgrammingError as error:
            if "one statement" in str(error):
                raise SqliteError("One statement only") from None
            raise SqliteError(f"The statement is not valid ({error})"[:200]) from None
        except sqlite3.DatabaseError as error:
            text = str(error)
            if "not authorized" in text or refused:
                shown = ", ".join(dict.fromkeys(refused)) or "that"
                raise SqliteError(
                    f"Not allowed here: {shown} cannot be read or done by this node (read-only, only the listed views)"
                ) from None
            if "interrupted" in text:
                raise SqliteError(f"The statement took longer than {timeout:g} s") from None
            raise SqliteError(f"The statement failed ({text})"[:200]) from None
    finally:
        conn.close()


async def run_query(
    source: DataSource, sql: str, values: Sequence[str] = (), **limits: Any
) -> QueryResult:
    """:func:`query` in a thread, bounded in time (the engine is interrupted at the limit, the thread ends with it)."""
    timeout = float(limits.get("timeout", 30.0))
    try:
        async with asyncio.timeout(timeout + 5):
            return await asyncio.to_thread(query, source, sql, values, **limits)
    except TimeoutError:
        raise SqliteError(f"The statement took longer than {timeout:g} s") from None


async def run_sqlite(
    config: Mapping[str, Any], sources: Mapping[str, DataSource], *, view: RunView | None = None
) -> NodeResult:
    """The SQLite node: its query with the values of its lines (references resolved here, then bound as parameters) on its data
    source; the rows are the node's data (``rows``) and, as JSON, its output."""
    started = time.monotonic()
    name = str(config.get("source") or APP_SOURCE)
    source = sources.get(name)
    if source is None:
        return failed(f"The data source '{name}' is not there")
    try:
        values = [
            (view or RunView()).render(line)
            for line in str(config.get("values") or "").splitlines()
        ]
    except ContextError as error:
        return failed(str(error))
    try:
        result = await run_query(
            source,
            str(config.get("query") or ""),
            values,
            blocked=blocked_names(str(config.get("blocked") or "")),
            timeout=float(config.get("timeout_seconds") or 30),
            max_rows=int(config.get("max_rows") or 100),
        )
    except SqliteError as error:
        return failed(str(error), duration=time.monotonic() - started)
    return NodeResult(
        "pass",
        output=json.dumps(result.rows, ensure_ascii=False, default=str),
        data=result.to_data(),
        duration=time.monotonic() - started,
    )

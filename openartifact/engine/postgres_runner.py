"""Runs one SQL statement on a Postgres database for the Postgres node and the Postgres Tool (ADR-041).

The connection URL comes from a secret. Only a plain connection is accepted (host, port, database, user,
password, ``sslmode``, ``sslrootcert=system``): no several hosts, no socket, no ``options``, ``service`` or
files. The host is resolved here and every address vetted like an HTTP node's (``http_runner``); the connection
goes to the vetted address (``hostaddr``) while the name stays the TLS name, so the name cannot resolve to
something else between the check and the connection.

The statement is the author's text and uses ``$1``, ``$2``, ...; the values travel as parameters of the extended
protocol and are never part of the text. The extended protocol also allows one statement only. By default the
statement runs in a ``READ ONLY`` transaction that is rolled back, and a first query has run before it, so the
server refuses a change of the mode from inside the statement. With ``allow_write`` the transaction is committed
when the statement succeeds. The server's statement timeout and the caller's time limit bound the time; rows are
read one by one and reading stops, by cancelling the statement, at ``max_rows`` or ``max_bytes``.

Nothing in an error text is the URL, the user, the password or the address: connection failures are reported in
words, and the password and the URL are scrubbed from anything else.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg import conninfo
from psycopg import errors as pg_errors

from openartifact.credentials.refs import mask_text
from openartifact.engine.context import ContextError, RunView
from openartifact.engine.http_runner import AddressRefusedError, vetted_addresses
from openartifact.engine.results import NodeResult, failed

#: What the node keeps of a result (the run context holds 64 KiB in all).
RESULT_LIMIT_BYTES = 48 * 1024
_ALLOWED = ("host", "port", "dbname", "user", "password", "sslmode", "sslrootcert")
#: Accepted and ignored: the connection's own time limit and name are set here.
_IGNORED = ("connect_timeout", "application_name")
_SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_$\u0080-\U0010ffff]")


class PostgresError(Exception):
    """The statement could not be run; the message is safe to show (no URL, user, password or address)."""


@dataclass(frozen=True)
class Target:
    """The parts of a connection URL that are used."""

    host: str
    port: int
    dbname: str | None
    user: str | None
    password: str | None
    sslmode: str | None
    sslrootcert: str | None = None


def parse_connection(url: str) -> Target:
    """The connection URL as a :class:`Target`; :class:`PostgresError` for anything that is not a plain one."""
    text = url.strip()
    if not text:
        raise PostgresError("The connection URL is empty")
    if not text.lower().startswith(("postgresql://", "postgres://")):
        raise PostgresError("The connection URL must look like postgresql://user:password@host/db")
    try:
        found = conninfo.conninfo_to_dict(text)
    except (psycopg.ProgrammingError, ValueError):
        raise PostgresError(
            "The connection URL is not valid: use postgresql://user:password@host:5432/db"
        ) from None
    for key in found:
        if key not in _ALLOWED and key not in _IGNORED:
            raise PostgresError(
                f"The connection URL uses '{key}', which is not accepted "
                f"(allowed: {', '.join(_ALLOWED)})"
            )
    host = str(found.get("host") or "")
    port = str(found.get("port") or "5432")
    if not host:
        raise PostgresError("The connection URL has no host")
    if "," in host or "," in port:
        raise PostgresError("The connection URL names one host only")
    if host.startswith("/") or "/" in host:
        raise PostgresError("The host must be a name or an address, not a socket path")
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise PostgresError("The port of the connection URL is not valid")
    sslmode = found.get("sslmode")
    if sslmode is not None and sslmode not in _SSL_MODES:
        raise PostgresError(f"sslmode must be one of: {', '.join(_SSL_MODES)}")
    sslrootcert = found.get("sslrootcert")
    if sslrootcert is not None and sslrootcert != "system":
        raise PostgresError("sslrootcert can only be 'system' (no file can be named)")
    return Target(
        host,
        int(port),
        found.get("dbname") or None,
        found.get("user") or None,
        found.get("password") or None,
        sslmode,
        sslrootcert,
    )


# ── bind parameters ──────────────────────────────────────────────────


def _end_quoted(sql: str, start: int, quote: str, backslash: bool) -> int:
    """The index after the quoted text that begins at ``start`` (a doubled quote does not end it)."""
    i = start + 1
    while i < len(sql):
        char = sql[i]
        if backslash and char == "\\":
            i += 2
            continue
        if char == quote:
            if sql[i + 1 : i + 2] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return len(sql)


def _end_block_comment(sql: str, start: int) -> int:
    depth, i = 0, start
    while i < len(sql):
        if sql.startswith("/*", i):
            depth, i = depth + 1, i + 2
        elif sql.startswith("*/", i):
            depth, i = depth - 1, i + 2
            if depth == 0:
                return i
        else:
            i += 1
    return len(sql)


_PARAMETER = re.compile(r"\$([0-9]+)")
_DOLLAR_QUOTE = re.compile(r"\$([A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_\u0080-\U0010ffff]*)?\$")


def _pieces(sql: str) -> list[tuple[str, int | None]]:
    """``sql`` as pieces: ``(text, None)`` of anything that is not a placeholder, ``("", n)`` for ``$n``."""
    pieces: list[tuple[str, int | None]] = []
    i, plain_from = 0, 0

    def flush(upto: int) -> None:
        if upto > plain_from:
            pieces.append((sql[plain_from:upto], None))

    while i < len(sql):
        char = sql[i]
        previous = sql[i - 1] if i else ""
        after_name = bool(previous) and bool(_IDENTIFIER.fullmatch(previous))
        if char == "'":
            escaped = previous in ("e", "E") and not (
                i >= 2 and _IDENTIFIER.fullmatch(sql[i - 2]) is not None
            )
            i = _end_quoted(sql, i, "'", escaped)
        elif char == '"':
            i = _end_quoted(sql, i, '"', False)
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
        elif sql.startswith("/*", i):
            i = _end_block_comment(sql, i)
        elif char == "$" and not after_name:
            parameter = _PARAMETER.match(sql, i)
            quote = _DOLLAR_QUOTE.match(sql, i)
            if parameter:
                flush(i)
                pieces.append(("", int(parameter.group(1))))
                i = plain_from = parameter.end()
            elif quote:
                closing = sql.find(quote.group(0), quote.end())
                i = len(sql) if closing < 0 else closing + len(quote.group(0))
            else:
                i += 1
        else:
            i += 1
    flush(len(sql))
    return pieces


def bind_values(sql: str, values: Sequence[str]) -> tuple[str, dict[str, str] | None]:
    """The statement and the parameters as the driver wants them.

    ``$n`` (outside strings, comments, quoted names and dollar quotes) becomes ``%(pn)s`` and every ``%`` of
    the text is doubled; the values are the parameters ``p1``, ``p2``, .... Without values the statement is
    left alone. A placeholder without a value, or a value no placeholder uses, is an error (the server would
    refuse it with a less helpful text).
    """
    pieces = _pieces(sql)
    used = {n for _, n in pieces if n is not None}
    wanted = max(used) if used else 0
    if wanted > len(values):
        given = (
            "no value is"
            if not values
            else f"only {len(values)} value{'s are' if len(values) > 1 else ' is'}"
        )
        raise PostgresError(f"The query uses ${wanted} but {given} given")
    for number in range(1, len(values) + 1):
        if number not in used:
            raise PostgresError(f"Value {number} is not used by the query (no ${number} in it)")
    if not values:
        return sql, None
    text = "".join(
        piece.replace("%", "%%") if number is None else f"%(p{number})s" for piece, number in pieces
    )
    return text, {f"p{n}": value for n, value in enumerate(values, start=1)}


# ── JSON ─────────────────────────────────────────────────────────────


def jsonable(value: Any) -> Any:
    """``value`` as JSON: numbers and text as they are, decimals as text (no precision lost), moments as ISO
    text, ``bytea`` as ``\\x...``, anything else as its text; lists and objects item by item."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | dt_time):
        return value.isoformat()
    if isinstance(value, timedelta | UUID | ipaddress.IPv4Address | ipaddress.IPv6Address):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return "\\x" + bytes(value).hex()
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return str(value)


# ── running ──────────────────────────────────────────────────────────


@dataclass
class QueryResult:
    """What a statement returned: the rows as objects, and whether they were all there."""

    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: The rows returned, or for a statement without rows the number of rows it changed (when changes are
    #: allowed: a read-only statement has no such count).
    row_count: int = 0
    truncated: bool = False

    def to_data(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "row_count": self.row_count,
            "truncated": self.truncated,
        }


def _unique(names: Sequence[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        unique.append(name if count == 1 else f"{name}_{count}")
    return unique


def _why_not_connected(error: Exception) -> str:
    text = str(error).lower()
    if "password authentication failed" in text or "authentication" in text:
        return "the user or the password was refused"
    if "does not exist" in text and "database" in text:
        return "the database does not exist"
    if "ssl" in text or "tls" in text:
        return "the TLS negotiation failed (check sslmode)"
    if "timeout" in text or "timed out" in text:
        return "the connection timed out"
    if "refused" in text:
        return "the connection was refused"
    if "no pg_hba.conf entry" in text:
        return "the server does not accept this user from here"
    return "the connection failed"


async def _connect(
    target: Target, addresses: list[Any], timeout: float
) -> psycopg.AsyncConnection[Any]:
    """The first of the vetted addresses that takes the connection."""
    settings: dict[str, Any] = {
        "host": target.host,
        "port": target.port,
        "dbname": target.dbname,
        "user": target.user,
        "password": target.password,
        "sslmode": target.sslmode,
        "sslrootcert": target.sslrootcert,
        "connect_timeout": max(2, math.ceil(timeout)),
        "application_name": "OpenArtifact",
        "gssencmode": "disable",
    }
    settings = {key: value for key, value in settings.items() if value is not None}
    last: Exception | None = None
    for address in addresses:
        try:
            conn: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
                **settings, hostaddr=str(address), autocommit=False
            )
            return conn
        except psycopg.OperationalError as error:
            last = error
    raise PostgresError(
        f"Could not connect to the database: {_why_not_connected(last or Exception())}"
    )


def _failed(error: psycopg.Error, *, timeout: float, write: bool) -> PostgresError:
    code = error.sqlstate or ""
    if isinstance(error, pg_errors.QueryCanceled):
        return PostgresError(f"Timeout after {timeout:g} s: the statement was stopped")
    message = (error.diag.message_primary or str(error)).strip().splitlines()[0][:400]
    text = f"{code}: {message}" if code else message
    if isinstance(error, pg_errors.ReadOnlySqlTransaction) or code == "25006":
        text += " (the node is read-only: turn on 'Allow changes' to write)"
    return PostgresError(text)


class _Rows:
    """Collects rows up to the limits; ``full`` says when the next one does not fit."""

    def __init__(self, max_rows: int, max_bytes: int) -> None:
        self.rows: list[dict[str, Any]] = []
        self.columns: list[str] = []
        self.truncated = False
        self._size = 2
        self._max_rows, self._max_bytes = max_rows, max_bytes

    def add(self, record: Sequence[Any]) -> bool:
        """Keep the row; ``False`` (and truncated) when it does not fit."""
        row = {name: jsonable(value) for name, value in zip(self.columns, record, strict=False)}
        cost = len(json.dumps(row, ensure_ascii=False).encode("utf-8")) + 1
        if len(self.rows) >= self._max_rows or self._size + cost > self._max_bytes:
            self.truncated = True
            return False
        self.rows.append(row)
        self._size += cost
        return True

    def result(self, count: int) -> QueryResult:
        return QueryResult(self.columns, self.rows, count, self.truncated)


async def _stream(
    conn: psycopg.AsyncConnection[Any],
    statement: str,
    params: dict[str, str] | None,
    max_rows: int,
    max_bytes: int,
) -> QueryResult:
    """A read-only statement: rows one by one, and the statement is cancelled when the limit is reached."""
    rows = _Rows(max_rows, max_bytes)
    async with conn.cursor() as cursor:
        try:
            async for record in cursor.stream(statement, params):
                if rows.truncated:
                    continue  # the statement is being cancelled; what still arrives is dropped
                if not rows.columns and cursor.description:
                    rows.columns = _unique([column.name for column in cursor.description])
                if not rows.add(record):
                    conn.cancel()  # nobody wants the rest of it
        except pg_errors.QueryCanceled:
            if not rows.truncated:
                raise
        except psycopg.ProgrammingError as error:
            # the driver's own complaint (no server code) that the statement gave no result set at all
            if error.sqlstate is not None:
                raise
    return rows.result(len(rows.rows))


async def _fetch(
    conn: psycopg.AsyncConnection[Any],
    statement: str,
    params: dict[str, str] | None,
    max_rows: int,
    max_bytes: int,
) -> QueryResult:
    """A statement that may change data: the server runs it to the end (it is committed whole), and the
    answer, with the number of rows it changed, is kept up to the limits."""
    rows = _Rows(max_rows, max_bytes)
    async with conn.cursor() as cursor:
        # prepare=True: the extended protocol, which takes one statement only, also without parameters
        await cursor.execute(statement, params, prepare=True)
        if not cursor.description:
            return rows.result(max(cursor.rowcount, 0))
        rows.columns = _unique([column.name for column in cursor.description])
        for record in await cursor.fetchall():
            if not rows.add(record):
                break
    return rows.result(len(rows.rows))


async def _execute(
    target: Target,
    addresses: list[Any],
    statement: str,
    params: dict[str, str] | None,
    *,
    allow_write: bool,
    timeout: float,
    max_rows: int,
    max_bytes: int,
) -> QueryResult:
    conn = await _connect(target, addresses, timeout)
    finished = False
    try:
        if not allow_write:
            await conn.execute("SET TRANSACTION READ ONLY")
        # a query before the user's statement: from then on the server refuses SET TRANSACTION READ WRITE
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
            (str(int(timeout * 1000)), str(int(timeout * 1000))),
        )
        read = _fetch if allow_write else _stream
        result = await read(conn, statement, params, max_rows, max_bytes)
        if allow_write:
            await conn.commit()
        else:
            await conn.rollback()
        finished = True
        return result
    except psycopg.Error as error:
        raise _failed(error, timeout=timeout, write=allow_write) from None
    finally:
        if not finished:
            with contextlib.suppress(Exception):
                conn.cancel()  # whatever is still running on the server stops with the connection
        with contextlib.suppress(Exception):
            await conn.close()


async def run_query(
    url: str,
    sql: str,
    values: Sequence[str] = (),
    *,
    allow_write: bool = False,
    allow_private: bool = False,
    timeout: float = 30,
    max_rows: int = 100,
    max_bytes: int = RESULT_LIMIT_BYTES,
) -> QueryResult:
    """Run ``sql`` with ``values`` as its parameters; :class:`PostgresError` says why it could not.

    ``timeout`` bounds everything (resolving, connecting, the statement); on the server the same time is the
    statement timeout and the statement is cancelled when the time is up.
    """
    if not sql.strip():
        raise PostgresError("The query is empty")
    secrets = [url, parse_password(url)]
    try:
        target = parse_connection(url)
        statement, params = bind_values(sql, values)
        try:
            async with asyncio.timeout(timeout):
                addresses = await vetted_addresses(target.host, target.port, allow_private)
                return await _execute(
                    target,
                    addresses,
                    statement,
                    params,
                    allow_write=allow_write,
                    timeout=timeout,
                    max_rows=max_rows,
                    max_bytes=max_bytes,
                )
        except AddressRefusedError as error:
            raise PostgresError(str(error)) from None
        except TimeoutError:
            raise PostgresError(f"Timeout after {timeout:g} s") from None
    except PostgresError as error:
        raise PostgresError(mask_text(str(error), [s for s in secrets if s])) from None


def parse_password(url: str) -> str:
    """The password of a connection URL (empty when there is none or the URL is not readable)."""
    try:
        return str(conninfo.conninfo_to_dict(url.strip()).get("password") or "")
    except (psycopg.ProgrammingError, ValueError):
        return ""


# ── the node ─────────────────────────────────────────────────────────


async def run_postgres(
    config: dict[str, Any], url: str, *, view: RunView | None = None, operator_allows_private: bool
) -> NodeResult:
    """The Postgres node: its query with the values of its lines (references resolved here, then bound as
    parameters) on the database of ``url``; the rows are the node's data (``rows``) and, as JSON, its output."""
    started = time.monotonic()
    try:
        values = [
            (view or RunView()).render(line)
            for line in str(config.get("values") or "").splitlines()
        ]
    except ContextError as error:
        return failed(str(error))
    try:
        result = await run_query(
            url,
            str(config.get("query") or ""),
            values,
            allow_write=bool(config.get("allow_write")),
            allow_private=bool(config.get("allow_private")) and operator_allows_private,
            timeout=float(config.get("timeout_seconds") or 30),
            max_rows=int(config.get("max_rows") or 100),
        )
    except PostgresError as error:
        return failed(str(error), duration=time.monotonic() - started)
    return NodeResult(
        "pass",
        output=json.dumps(result.rows, ensure_ascii=False),
        data=result.to_data(),
        duration=time.monotonic() - started,
    )

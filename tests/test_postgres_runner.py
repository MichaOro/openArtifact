"""The Postgres executor core (ADR-041): the connection URL, bind parameters, read-only by the server, bounds.

The pure parts run everywhere; the rest runs against a real server (``tests/postgres_support.py``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from openartifact.engine import postgres_runner
from openartifact.engine.postgres_runner import (
    PostgresError,
    bind_values,
    jsonable,
    parse_connection,
    run_query,
)
from tests.postgres_support import PgDb

# ── the connection URL ───────────────────────────────────────────────


def test_a_connection_url_is_read_into_its_parts() -> None:
    target = parse_connection(
        "postgresql://app%40x:p%2Fw@db.example.org:6543/tickets?sslmode=require"
    )
    assert (target.host, target.port, target.user, target.password, target.dbname) == (
        "db.example.org",
        6543,
        "app@x",
        "p/w",
        "tickets",
    )
    assert target.sslmode == "require"
    plain = parse_connection("postgres://u:p@[::1]/d")
    assert (plain.host, plain.port, plain.sslmode) == ("::1", 5432, None)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("mysql://u:p@h/d", "postgresql://"),
        ("postgresql://u:p@/d", "no host"),
        ("postgresql://u:p@h1,h2/d", "one host"),
        ("postgresql://u:p@h:5432,5433/d", "one host"),
        ("postgresql://u:p@%2Fvar%2Frun%2Fpostgresql/d", "a name or an address"),
        ("postgresql://u:p@h/d?options=-c%20default_transaction_read_only%3Doff", "options"),
        ("postgresql://u:p@h/d?service=mine", "service"),
        ("postgresql://u:p@h/d?hostaddr=10.0.0.1", "hostaddr"),
        ("postgresql://u:p@h/d?sslcert=%2Fetc%2Fpasswd", "sslcert"),
        ("postgresql://u:p@h/d?passfile=%2Froot%2F.pgpass", "passfile"),
        ("postgresql://u:p@h/d?sslrootcert=%2Fetc%2Fssl%2Fca.pem", "sslrootcert"),
        ("postgresql://u:p@h/d?sslmode=maybe", "sslmode"),
        ("not a url at all", "postgresql://"),
        ("", "empty"),
    ],
)
def test_a_connection_url_that_could_reach_beyond_a_plain_connection_is_refused(
    url: str, message: str
) -> None:
    with pytest.raises(PostgresError, match=message):
        parse_connection(url)


def test_the_system_certificates_may_be_named_but_no_file() -> None:
    assert parse_connection(
        "postgresql://u:p@h/d?sslmode=verify-full&sslrootcert=system"
    ).sslrootcert == ("system")


def test_a_refused_url_never_repeats_the_password() -> None:
    with pytest.raises(PostgresError) as caught:
        parse_connection("postgresql://u:hunter2-pass@h1,h2/d")
    assert "hunter2" not in str(caught.value)


# ── bind parameters ──────────────────────────────────────────────────


def test_placeholders_become_named_parameters_and_percent_signs_are_kept() -> None:
    sql, params = bind_values(
        "SELECT * FROM t WHERE a = $1 AND b LIKE '%' || $2 AND c = $1", ["x", "y"]
    )
    assert sql == "SELECT * FROM t WHERE a = %(p1)s AND b LIKE '%%' || %(p2)s AND c = %(p1)s"
    assert params == {"p1": "x", "p2": "y"}


def test_without_values_the_statement_goes_as_it_is() -> None:
    assert bind_values("SELECT '100%' AS rate", []) == ("SELECT '100%' AS rate", None)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT '$1' AS a, $1",  # inside a string
        "SELECT 'it''s $1' AS a, $1",
        "SELECT E'it\\'s $1' AS a, $1",  # a backslash escape in an E string
        'SELECT "col$1" FROM t WHERE x = $1',  # inside a quoted identifier
        "SELECT 1 -- $1 here\n, $1",  # a line comment
        "SELECT 1 /* $1 /* nested $1 */ still $1 */, $1",  # a nested block comment
        "SELECT $q$ $1 $q$, $1",  # a dollar-quoted string
        "SELECT $$ $1 $$, $1",
        "SELECT a$1 FROM t WHERE x = $1",  # an identifier may contain a dollar sign
    ],
)
def test_only_a_placeholder_outside_strings_comments_and_names_is_one(sql: str) -> None:
    converted, params = bind_values(sql, ["v"])
    assert converted.count("%(p1)s") == 1, converted
    assert params == {"p1": "v"}


def test_percent_signs_are_doubled_everywhere_when_values_are_bound() -> None:
    converted, _ = bind_values("SELECT '50%', $1 -- 5%\n, $$ 7% $$", ["v"])
    assert converted == "SELECT '50%%', %(p1)s -- 5%%\n, $$ 7%% $$"


@pytest.mark.parametrize(
    ("sql", "values", "message"),
    [
        ("SELECT $2", ["a"], r"uses \$2 but only 1 value"),
        ("SELECT $1", [], r"uses \$1 but no value"),
        ("SELECT $1", ["a", "b"], r"Value 2 is not used"),
        ("SELECT $2", ["a", "b"], r"Value 1 is not used"),
    ],
)
def test_the_values_must_match_the_placeholders(sql: str, values: list[str], message: str) -> None:
    with pytest.raises(PostgresError, match=message):
        bind_values(sql, values)


# ── JSON ─────────────────────────────────────────────────────────────


def test_values_become_json_without_losing_what_json_cannot_hold() -> None:
    moment = datetime(2026, 11, 23, 4, 5, 6, tzinfo=UTC)
    ident = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert jsonable(
        {
            "n": 5,
            "f": 1.5,
            "d": Decimal("12.50"),
            "t": moment,
            "u": ident,
            "b": b"\x00\xff",
            "none": None,
            "ok": True,
            "list": [Decimal("1.0"), {"x": moment}],
            "nan": float("nan"),
            "inf": float("inf"),
        }
    ) == {
        "n": 5,
        "f": 1.5,
        "d": "12.50",
        "t": "2026-11-23T04:05:06+00:00",
        "u": "12345678-1234-5678-1234-567812345678",
        "b": "\\x00ff",
        "none": None,
        "ok": True,
        "list": ["1.0", {"x": "2026-11-23T04:05:06+00:00"}],
        "nan": "nan",
        "inf": "inf",
    }


# ── against a real server ────────────────────────────────────────────


async def _run(db: PgDb, sql: str, *values: str, **options: Any) -> Any:
    options.setdefault("allow_private", True)  # the test server is on the loopback address
    return await run_query(db.url, sql, list(values), **options)


async def test_rows_come_back_as_a_list_of_objects_with_json_values(pg: PgDb) -> None:
    pg.sql(
        "CREATE TABLE t (id int, name text, price numeric, at timestamptz, extra jsonb, tags text[])"
    )
    pg.sql(
        "INSERT INTO t VALUES (1, 'Ann', 12.50, '2026-11-23 04:05:06+00', '{\"k\": [1, 2]}', '{a,b}'),"
        " (2, NULL, NULL, NULL, NULL, NULL)"
    )
    result = await _run(pg, "SELECT * FROM t ORDER BY id")
    assert result.columns == ["id", "name", "price", "at", "extra", "tags"]
    assert result.rows == [
        {
            "id": 1,
            "name": "Ann",
            "price": "12.50",
            "at": "2026-11-23T04:05:06+00:00",
            "extra": {"k": [1, 2]},
            "tags": ["a", "b"],
        },
        {"id": 2, "name": None, "price": None, "at": None, "extra": None, "tags": None},
    ]
    assert (result.truncated, result.row_count) == (False, 2)


async def test_two_columns_of_one_name_both_survive(pg: PgDb) -> None:
    result = await _run(pg, "SELECT 1 AS a, 2 AS a, 3 AS a")
    assert result.rows == [{"a": 1, "a_2": 2, "a_3": 3}]
    assert result.columns == ["a", "a_2", "a_3"]


async def test_a_value_is_a_parameter_so_it_cannot_change_the_statement(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id int, note text)")
    pg.sql("INSERT INTO t VALUES (1, 'one')")
    hostile = "x'; DROP TABLE t; --"
    result = await _run(pg, "SELECT $1 AS echoed, count(*) AS n FROM t", hostile)
    assert result.rows == [{"echoed": hostile, "n": 1}]
    assert pg.sql("SELECT count(*) FROM t") == [(1,)]  # the table is still there


async def test_a_text_value_is_converted_to_the_type_the_query_expects(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id int, note text)")
    pg.sql("INSERT INTO t VALUES (1, 'one'), (2, 'two')")
    assert (await _run(pg, "SELECT note FROM t WHERE id = $1", "2")).rows == [{"note": "two"}]
    assert (await _run(pg, "SELECT note FROM t WHERE note LIKE '%' || $1 || '%'", "w")).rows == [
        {"note": "two"}
    ]


async def test_a_statement_that_returns_no_rows_reports_what_it_did(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id int)")
    result = await _run(pg, "INSERT INTO t VALUES (1), (2)", allow_write=True)
    assert (result.rows, result.columns, result.row_count) == ([], [], 2)  # two rows changed
    assert pg.sql("SELECT count(*) FROM t") == [(2,)]


async def test_a_read_only_statement_without_a_result_set_is_not_an_error(pg: PgDb) -> None:
    result = await _run(pg, "DO $$ BEGIN PERFORM 1; END $$")
    assert (result.rows, result.columns, result.truncated) == ([], [], False)


async def test_returning_rows_of_a_change_are_returned_and_committed(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id serial, note text)")
    result = await _run(
        pg, "INSERT INTO t (note) VALUES ($1) RETURNING id", "kept", allow_write=True
    )
    assert result.rows == [{"id": 1}]
    assert pg.sql("SELECT note FROM t") == [("kept",)]


async def test_a_failing_change_is_rolled_back_whole(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id int PRIMARY KEY)")
    pg.sql("INSERT INTO t VALUES (1)")
    with pytest.raises(PostgresError, match="23505"):
        await _run(pg, "INSERT INTO t VALUES (2), (1)", allow_write=True)
    assert pg.sql("SELECT id FROM t") == [(1,)]


async def test_by_default_the_server_refuses_every_change_and_says_how_to_allow_it(
    pg: PgDb,
) -> None:
    pg.sql("CREATE TABLE t (id int)")
    with pytest.raises(PostgresError, match="read-only") as caught:
        await _run(pg, "INSERT INTO t VALUES (1)")
    assert "Allow changes" in str(caught.value)
    assert pg.sql("SELECT count(*) FROM t") == [(0,)]


@pytest.mark.parametrize(
    "attack",
    [
        "SET TRANSACTION READ WRITE",
        "SELECT set_config('transaction_read_only', 'off', true)",
        "DO $$ BEGIN SET TRANSACTION READ WRITE; CREATE TABLE zz (a int); END $$",
        "DO $$ BEGIN COMMIT; END $$",
        "SELECT 1; COMMIT; CREATE TABLE zz (a int)",
        "COMMIT; CREATE TABLE zz (a int)",
        "CREATE TABLE zz (a int)",
        "WITH x AS (INSERT INTO t VALUES (9) RETURNING 1) SELECT * FROM x",
    ],
)
async def test_read_only_is_the_servers_and_cannot_be_undone_from_inside_the_statement(
    pg: PgDb, attack: str
) -> None:
    pg.sql("CREATE TABLE t (id int)")
    with pytest.raises(PostgresError):
        await _run(pg, attack)
    assert pg.sql("SELECT to_regclass('zz')") == [(None,)]
    assert pg.sql("SELECT count(*) FROM t") == [(0,)]


async def test_one_statement_only_even_without_values(pg: PgDb) -> None:
    with pytest.raises(PostgresError, match="multiple commands"):
        await _run(pg, "SELECT 1; SELECT 2")


async def test_reading_stops_at_the_row_limit_by_cancelling_the_statement(pg: PgDb) -> None:
    endless = "WITH RECURSIVE r (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT n FROM r"
    began = time.monotonic()
    result = await _run(pg, endless, max_rows=5, timeout=20)
    assert [row["n"] for row in result.rows] == [1, 2, 3, 4, 5]
    assert result.truncated is True
    assert time.monotonic() - began < 10  # not by waiting for the end or the time limit


async def test_the_result_is_cut_at_the_byte_limit_and_says_so(pg: PgDb) -> None:
    result = await _run(
        pg, "SELECT repeat('x', 1000) AS wide FROM generate_series(1, 50)", max_bytes=5000
    )
    assert 1 <= len(result.rows) < 6
    assert result.truncated is True
    assert len(str(result.rows)) <= 6000


async def test_a_change_is_not_cancelled_by_the_row_limit(pg: PgDb) -> None:
    pg.sql("CREATE TABLE t (id int)")
    result = await _run(
        pg,
        "INSERT INTO t SELECT g FROM generate_series(1, 20) g RETURNING id",
        allow_write=True,
        max_rows=3,
    )
    assert len(result.rows) == 3 and result.truncated is True
    assert pg.sql("SELECT count(*) FROM t") == [(20,)]  # all of it was written and committed


async def test_a_statement_over_the_time_limit_fails_and_stops_on_the_server(pg: PgDb) -> None:
    began = time.monotonic()
    with pytest.raises(PostgresError, match=r"Timeout after 1 s"):
        await _run(pg, "SELECT pg_sleep(30)", timeout=1)
    assert time.monotonic() - began < 8
    for _ in range(50):  # the server notices the cancel at once; allow a moment
        if pg.activity("%pg_sleep(30)%") == 0:
            break
        await asyncio.sleep(0.1)
    assert pg.activity("%pg_sleep(30)%") == 0


async def test_the_statement_timeout_of_the_server_applies_too(pg: PgDb) -> None:
    # a statement that sets its own limit away inside a DO block is still stopped by the node's time limit
    with pytest.raises(PostgresError, match=r"Timeout after 1 s"):
        await _run(
            pg,
            "DO $$ BEGIN SET LOCAL statement_timeout = 0; PERFORM pg_sleep(30); END $$",
            timeout=1,
        )
    for _ in range(50):
        if pg.activity("%pg_sleep(30)%") == 0:
            break
        await asyncio.sleep(0.1)
    assert pg.activity("%pg_sleep(30)%") == 0


# ── errors and the network ───────────────────────────────────────────


async def test_a_sql_error_is_reported_with_its_code_and_message(pg: PgDb) -> None:
    with pytest.raises(PostgresError, match=r'42P01.*relation "nothere" does not exist'):
        await _run(pg, "SELECT * FROM nothere")


async def test_a_wrong_password_is_reported_without_url_user_or_password(pg: PgDb) -> None:
    pg.sql(f"CREATE ROLE {pg.role} LOGIN PASSWORD 'right-password'")
    wrong = pg.url_as(pg.role, "wrong-password")
    with pytest.raises(PostgresError) as caught:
        await run_query(wrong, "SELECT 1", [], allow_private=True)
    message = str(caught.value)
    assert "refused" in message
    for secret in ("wrong-password", pg.role, "127.0.0.1", wrong):
        assert secret not in message


async def test_a_database_that_does_not_exist_is_said_so(pg: PgDb) -> None:
    missing = pg.url.rsplit("/", 1)[0] + "/no_such_database"
    with pytest.raises(PostgresError, match="does not exist"):
        await run_query(missing, "SELECT 1", [], allow_private=True)


async def test_a_private_address_is_refused_unless_the_switch_says_otherwise(pg: PgDb) -> None:
    with pytest.raises(PostgresError, match="private network address"):
        await run_query(pg.url, "SELECT 1", [], allow_private=False)
    assert (await run_query(pg.url, "SELECT 1 AS one", [], allow_private=True)).rows == [{"one": 1}]


async def test_a_metadata_address_is_never_connected_to(pg: PgDb) -> None:
    with pytest.raises(PostgresError, match="cloud metadata address"):
        await run_query("postgresql://u:p@169.254.169.254/d", "SELECT 1", [], allow_private=True)


async def test_the_connection_goes_to_the_vetted_address_not_to_the_name(
    pg: PgDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name nobody can resolve connects only because the vetted address is what the driver is given."""
    seen: list[tuple[str, int]] = []

    async def vetted(host: str, port: int, allow_private: bool) -> list[Any]:
        import ipaddress

        seen.append((host, port))
        return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(postgres_runner, "vetted_addresses", vetted)
    port = pg.url.split("@", 1)[1].split("/")[0].rsplit(":", 1)[1]
    url = f"postgresql://oa:pw@db.pinned.invalid:{port}/{pg.name}"
    result = await run_query(url, "SELECT 1 AS one", [], allow_private=True)
    assert result.rows == [{"one": 1}]
    assert seen == [("db.pinned.invalid", int(port))]


async def test_nothing_of_the_url_is_left_in_an_unexpected_error(pg: PgDb) -> None:
    """The driver's own message may hold the URL: whatever fails, the secret is scrubbed from the text."""
    url = "postgresql://someone:s3cr3t-pw@127.0.0.1:1/nodb?sslmode=disable"
    with pytest.raises(PostgresError) as caught:
        await run_query(url, "SELECT 1", [], allow_private=True, timeout=5)
    for secret in ("s3cr3t-pw", "someone", url):
        assert secret not in str(caught.value)
    assert "refused" in str(caught.value) or "could not connect" in str(caught.value).lower()

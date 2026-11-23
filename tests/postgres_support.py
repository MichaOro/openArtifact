"""A real Postgres server for the tests (ADR-041).

``OA_TEST_POSTGRES_URL`` names a server (a role that may create databases, for example the service container
of the CI job). Without it a throwaway docker container is started on a random port of the loopback address
and removed afterwards. Without either the tests that need a server are skipped, saying so. Every test gets a
database of its own.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

IMAGE = "postgres:16-alpine"


def _started_container() -> tuple[str, str]:
    """(admin URL, container name) of a new throwaway server."""
    name = f"oa-test-pg-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=pw",
            "-e",
            "POSTGRES_USER=oa",
            "-p",
            "127.0.0.1:0:5432",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    shown = subprocess.run(
        ["docker", "port", name, "5432"], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    port = shown.rsplit(":", 1)[1]
    url = f"postgresql://oa:pw@127.0.0.1:{port}/postgres"
    deadline = time.monotonic() + 90
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            time.sleep(0.5)  # the image restarts the server once after initialising
            with psycopg.connect(url, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return url, name
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
                raise
            time.sleep(0.5)


@pytest.fixture(scope="session")
def postgres_admin_url() -> Iterator[str]:
    configured = os.environ.get("OA_TEST_POSTGRES_URL")
    if configured:
        yield configured
        return
    if shutil.which("docker") is None:
        pytest.skip("no Postgres: set OA_TEST_POSTGRES_URL or install docker")
    try:
        url, name = _started_container()
    except (subprocess.CalledProcessError, psycopg.OperationalError) as error:
        pytest.skip(f"no Postgres: the docker container did not start ({type(error).__name__})")
    yield url
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@dataclass
class PgDb:
    """A database of one test: its URL (as the owner) and a way to look at it as an administrator."""

    admin_url: str
    name: str

    @property
    def role(self) -> str:
        """The name of a role this test may create (roles belong to the server, so it is dropped afterwards)."""
        return f"r_{self.name}"

    @property
    def url(self) -> str:
        return urlsplit(self.admin_url)._replace(path=f"/{self.name}").geturl()

    def url_as(self, user: str, password: str) -> str:
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        return parts._replace(netloc=f"{user}:{password}@{host}:{parts.port}").geturl()

    def sql(self, statement: str, *params: Any) -> list[tuple[Any, ...]]:
        """Run a statement as the owner (committed); the rows it returns."""
        with psycopg.connect(self.url, autocommit=True) as conn:
            cur = conn.execute(statement, params or None)
            return cur.fetchall() if cur.description else []

    def activity(self, like: str) -> int:
        """How many statements of this database are running whose text matches ``like``."""
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            row = conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND state = 'active' "
                "AND query LIKE %s AND pid <> pg_backend_pid()",
                (self.name, like),
            ).fetchone()
        return int(row[0]) if row else 0


@pytest.fixture
def pg(postgres_admin_url: str) -> Iterator[PgDb]:
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield PgDb(postgres_admin_url, name)
    finally:
        with psycopg.connect(postgres_admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f'DROP ROLE IF EXISTS "{PgDb(postgres_admin_url, name).role}"')

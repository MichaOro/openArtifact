"""The credential store: encryption, API, references in nodes, masking of results, migration."""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import threading
from collections.abc import Generator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from alembic import command
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.credentials.crypto import SecretUnreadableError, decrypt, encrypt
from openartifact.credentials.refs import (
    SecretReferenceError,
    check_url_references,
    mask_data,
    mask_text,
    parse_name_lines,
    substitute,
)
from openartifact.credentials.store import SecretResolveError
from openartifact.engine.executors import Limits, _code, _http
from openartifact.graph.node_types import node_type
from openartifact.models import NodeKind
from tests.helpers import alembic_config
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import graph_url as _url
from tests.helpers import make_task as _make_task
from tests.helpers import node as _node
from tests.helpers import post as _post
from tests.helpers import wait_for_run as _wait
from tests.test_execution_nodes import _definition, _start, _use, _work

TOKEN = "secret-store-token-" + "x" * 20
KEY = "k" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
VALUE = "s3cr3t-Value/with+odd chars&=?"


# ── crypto ───────────────────────────────────────────────────────────


def test_encryption_round_trips_and_uses_a_fresh_nonce_each_time() -> None:
    first, second = encrypt(KEY, "API_KEY", VALUE), encrypt(KEY, "API_KEY", VALUE)
    assert first != second
    assert VALUE.encode() not in first
    assert decrypt(KEY, "API_KEY", first) == decrypt(KEY, "API_KEY", second) == VALUE


def test_a_wrong_key_a_tampered_value_and_another_name_do_not_decrypt() -> None:
    blob = encrypt(KEY, "API_KEY", VALUE)
    with pytest.raises(SecretUnreadableError):
        decrypt("another-key", "API_KEY", blob)
    with pytest.raises(SecretUnreadableError):
        decrypt(KEY, "OTHER", blob)  # the name is bound as associated data
    flipped = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(SecretUnreadableError):
        decrypt(KEY, "API_KEY", flipped)
    for broken in (b"", b"\x01short", b"\x02" + blob[1:]):
        with pytest.raises(SecretUnreadableError):
            decrypt(KEY, "API_KEY", broken)


# ── references and masking ───────────────────────────────────────────


def test_names_and_lines_are_validated() -> None:
    assert parse_name_lines("A\n\n B_1 \nA") == ["A", "B_1"]
    for bad in ("lower", "1A", "A-B", "A B", "OPENARTIFACT_X", "PATH", "HOME"):
        with pytest.raises(SecretReferenceError):
            parse_name_lines(bad)
    with pytest.raises(SecretReferenceError):
        parse_name_lines("\n".join(f"N{i}" for i in range(33)))


def test_a_reference_is_allowed_after_the_host_only() -> None:
    check_url_references("https://example.org/path?token=${secret:TOKEN}")
    check_url_references("https://example.org?token=${secret:TOKEN}")
    for bad in (
        "https://${secret:HOST}/x",
        "https://example.org:${secret:PORT}/x",
        "${secret:BASE}/x",
        "https://user:${secret:PW}@example.org/",
        "https://example.org/${secret:bad}",
    ):
        with pytest.raises(SecretReferenceError):
            check_url_references(bad)


def test_substitution_percent_encodes_only_in_urls() -> None:
    values = {"A": "a b&c"}
    assert substitute("x=${secret:A}", values) == "x=a b&c"
    assert substitute("x=${secret:A}", values, percent_encode=True) == "x=a%20b%26c"


def test_masking_covers_the_usual_forms() -> None:
    forms = [
        VALUE,
        quote(VALUE, safe=""),
        base64.b64encode(VALUE.encode()).decode(),
        base64.urlsafe_b64encode(VALUE.encode()).decode().rstrip("="),
        json.dumps(VALUE)[1:-1],
    ]
    text = "\n".join(f"line {i}: {form} end" for i, form in enumerate(forms))
    masked = mask_text(text, [VALUE])
    assert masked.count("***") == len(forms)
    assert "s3cr3t" not in masked
    assert mask_data({"k": [VALUE, 1, {VALUE: None}]}, [VALUE]) == {"k": ["***", 1, {"***": None}]}


def test_a_reference_without_a_value_stays_literal() -> None:
    assert substitute("${secret:A} ${secret:B}", {"A": "x"}) == "x ${secret:B}"
    assert substitute("?k=${secret:B}", {}, percent_encode=True) == "?k=${secret:B}"


# ── the application with a token and a key ───────────────────────────


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": KEY, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _put(client: TestClient, name: str, value: str = VALUE) -> Any:
    return client.put(f"/api/secrets/{name}", json={"value": value})


def test_the_api_stores_lists_and_never_returns_a_value(
    secured: TestClient, migrated_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    created = _put(secured, "API_KEY")
    assert created.status_code == 201
    assert set(created.json()) == {"name", "created_at", "updated_at"}
    assert created.json()["created_at"].endswith("Z") and created.json()["updated_at"].endswith("Z")
    replaced = _put(secured, "API_KEY", "another-value-1")
    assert replaced.status_code == 200
    listed = secured.get("/api/secrets")
    assert [s["name"] for s in listed.json()] == ["API_KEY"]
    everything = created.text + replaced.text + listed.text
    assert VALUE not in everything and "another-value-1" not in everything
    assert VALUE not in caplog.text and "another-value-1" not in caplog.text
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        (blob,) = conn.execute("SELECT value FROM secrets").fetchone()
    assert b"another-value-1" not in blob
    assert secured.delete("/api/secrets/API_KEY").status_code == 204
    assert secured.delete("/api/secrets/API_KEY").status_code == 404
    assert secured.get("/api/secrets").json() == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("lower", "v"),
        ("1A", "v"),
        ("A" * 65, "v"),
        ("OK", ""),
        ("OK", "x" * 8193),
        ("OK", "a\x00b"),
    ],
)
def test_names_and_values_are_validated(secured: TestClient, name: str, value: str) -> None:
    response = _put(secured, name, value)
    assert response.status_code == 422
    assert value not in response.text or value == ""


def test_the_value_may_be_8_kib(secured: TestClient) -> None:
    assert _put(secured, "BIG", "x" * 8192).status_code == 201


def test_without_a_token_nothing_can_be_saved(client: TestClient) -> None:
    response = client.put("/api/secrets/API_KEY", json={"value": "v"})
    assert response.status_code == 409
    assert "OPENARTIFACT_API_TOKEN" in response.json()["detail"]
    assert client.get("/api/secrets").json() == []


def test_the_secrets_are_behind_the_access_gate(secured: TestClient) -> None:
    assert secured.get("/api/secrets", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert (
        secured.get("/api/v1/secrets", headers={"Authorization": "Bearer nope"}).status_code == 401
    )


def test_the_integration_api_lists_writes_and_deletes(secured: TestClient) -> None:
    assert secured.put("/api/v1/secrets/TOKEN_A", json={"value": VALUE}).status_code == 201
    listed = secured.get("/api/v1/secrets")
    assert [s["name"] for s in listed.json()] == ["TOKEN_A"] and VALUE not in listed.text
    assert secured.delete("/api/v1/secrets/TOKEN_A").status_code == 204


def test_the_mcp_server_lists_names_and_has_no_way_to_read_a_value(secured: TestClient) -> None:
    _put(secured, "API_KEY")
    mcp = {**HEADERS, "Accept": "application/json, text/event-stream"}

    def call(method: str, params: dict[str, Any]) -> Any:
        response = secured.post(
            "/mcp",
            headers=mcp,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        return response.json()

    tools = {t["name"] for t in call("tools/list", {})["result"]["tools"]}
    assert "list_secrets" in tools
    assert not {t for t in tools if "secret" in t} - {"list_secrets"}
    result = call("tools/call", {"name": "list_secrets", "arguments": {}})
    assert "API_KEY" in str(result) and VALUE not in str(result)


def test_node_settings_validate_references_on_save(secured: TestClient) -> None:
    action = _post(secured, "/api/actions", name="A")
    http = _node(secured, action, "http")
    code = _node(secured, action, "code")

    def patch(node: dict[str, Any], **config: Any) -> int:
        response = secured.patch(f"{_url(action)}/nodes/{node['id']}", json={"config": config})
        assert VALUE not in response.text
        return response.status_code

    assert patch(http, url="https://example.org/x?k=${secret:API_KEY}") == 200
    assert patch(http, headers="Authorization: Bearer ${secret:API_KEY}") == 200
    assert patch(http, body='{"k": "${secret:API_KEY}"}') == 200
    assert patch(http, url="https://${secret:API_KEY}/x") == 422
    assert patch(http, body="${secret:lower}") == 422
    assert patch(code, secrets="API_KEY\nOTHER") == 200
    assert patch(code, secrets="not a name") == 422
    assert patch(code, secrets="OPENARTIFACT_API_TOKEN") == 422
    assert patch(code, secrets="") == 200


def test_the_code_node_has_a_secrets_setting_and_old_nodes_still_read(secured: TestClient) -> None:
    settings = {s["key"]: s for s in node_type(NodeKind.CODE).describe()["settings"]}
    assert settings["secrets"]["type"] == "lines" and settings["secrets"]["stored_in"] == "config"
    assert "${secret:NAME}" in settings["code"]["help"]
    assert node_type(NodeKind.CODE).effective_config({"code": "x"})["secrets"] == ""


# ── executors ────────────────────────────────────────────────────────


class _Echo(BaseHTTPRequestHandler):
    hits: ClassVar[list[tuple[str, dict[str, str], bytes]]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Echo.hits.append((self.path, dict(self.headers.items()), body))
        reply = json.dumps(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": body.decode()}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = do_POST  # noqa: N815

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def echo() -> Iterator[int]:
    _Echo.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _limits(**values: str) -> Limits:
    async def resolve(names: Any) -> dict[str, str]:
        missing = [n for n in names if n not in values]
        if missing:
            raise SecretResolveError(f"Secret {missing[0]} does not exist")
        return {n: values[n] for n in names}

    return Limits(http_allow_private_networks=True, secrets=resolve)


def _http_node(**config: Any) -> dict[str, Any]:
    return {"id": "n", "config": {"method": "POST", "timeout_seconds": 10, **config}}


async def test_http_references_are_put_into_url_headers_and_body_and_masked(echo: int) -> None:
    node = _http_node(
        url=f"http://127.0.0.1:{echo}/p?token=${{secret:TOKEN}}",
        headers="Authorization: Bearer ${secret:TOKEN}",
        body='{"k": "${secret:TOKEN}"}',
    )
    result = await _http(node, _limits(TOKEN=VALUE))
    path, headers, body = _Echo.hits[0]
    assert path == f"/p?token={quote(VALUE, safe='')}"
    assert headers["Authorization"] == f"Bearer {VALUE}"
    assert body.decode() == '{"k": "' + VALUE + '"}'
    # the server echoed every form back: none of them may reach the result
    assert result.outcome == "pass"
    assert "***" in result.output
    for form in (VALUE, quote(VALUE, safe=""), json.dumps(VALUE)[1:-1]):
        assert form not in result.output


async def test_an_error_text_that_holds_the_url_is_masked() -> None:
    node = _http_node(url="http://127.0.0.1:1/x?token=${secret:TOKEN}")
    result = await _http(node, _limits(TOKEN=VALUE))
    assert result.outcome == "fail"
    assert VALUE not in str(result) and quote(VALUE, safe="") not in str(result)


async def test_a_reference_in_the_host_is_refused_without_a_request() -> None:
    result = await _http(_http_node(url="http://${secret:HOSTX}/x"), _limits(HOSTX="localhost"))
    assert result.outcome == "fail" and "not in the scheme or the host" in str(result.reason)


async def test_an_unknown_secret_fails_the_node_with_its_name() -> None:
    result = await _http(_http_node(url="http://127.0.0.1:1/${secret:MISSING}"), _limits())
    assert (result.outcome, result.reason) == ("fail", "Secret MISSING does not exist")
    config: dict[str, Any] = {"language": "sh", "code": "true", "timeout_seconds": 5}
    code = {"id": "n", "config": {**config, "secrets": "MISSING"}}
    result = await _code(code, _limits())
    assert (result.outcome, result.reason) == ("fail", "Secret MISSING does not exist")


async def test_a_header_value_with_a_newline_cannot_add_a_header() -> None:
    node = _http_node(url="http://127.0.0.1:1/x", headers="X-A: ${secret:S}")
    result = await _http(node, _limits(S="a\r\nX-Evil: 1"))
    assert result.outcome == "fail" and "control character" in str(result.reason)
    assert "X-Evil" not in str(result.reason)


async def test_a_code_node_gets_exactly_its_secrets_as_variables_and_they_are_masked() -> None:
    code = (
        'echo "key=$API_KEY"\n'
        'echo "other=${OTHER:-unset}"\n'
        "env | grep -c '^OPENARTIFACT_' || true\n"
        'echo "{\\"ok\\": true, \\"data\\": {\\"seen\\": \\"$API_KEY\\"}}"\n'
    )
    node = {
        "id": "n",
        "config": {"language": "sh", "code": code, "timeout_seconds": 10, "secrets": "API_KEY"},
    }
    result = await _code(node, _limits(API_KEY="abc123XYZ", OTHER="never-given"))
    assert result.outcome == "pass"
    assert "key=***" in result.output and "other=unset" in result.output
    assert "abc123XYZ" not in result.output and "never-given" not in result.output
    assert result.data == {"seen": "***"}
    # only the random marker of the cleanup is an OPENARTIFACT_ variable
    assert "\n1\n" in result.output


async def test_the_script_text_is_not_interpolated() -> None:
    node = {
        "id": "n",
        "config": {"language": "sh", "code": "echo '${secret:S}'", "timeout_seconds": 5},
    }
    result = await _code(node, _limits(S="zzzz-value"))
    assert result.output.strip() == "${secret:S}"


async def test_the_values_are_masked_in_the_log_while_the_node_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from openartifact.logging_config import _SensitiveFilter, masked_in_logs

    record = logging.LogRecord(
        "openartifact.x", logging.INFO, "f", 1, "got %s", ("hunter2!",), None
    )
    with masked_in_logs(["hunter2!"]):
        _SensitiveFilter().filter(record)
    assert record.msg == "got ***"
    after = logging.LogRecord("openartifact.x", logging.INFO, "f", 1, "got hunter2!", (), None)
    _SensitiveFilter().filter(after)
    assert after.msg == "got hunter2!"


# ── through the engine ───────────────────────────────────────────────


def _snapshots(settings: Settings) -> list[str]:
    path = settings.data_dir / settings.database_filename
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT snapshot FROM pipeline_runs")]


def test_a_run_uses_a_secret_and_the_snapshot_and_results_hold_references_only(
    secured: TestClient, migrated_settings: Settings, echo: int
) -> None:
    assert _put(secured, "API_KEY").status_code == 201
    pipeline, task = _pipeline(secured, stages=1), _make_task(secured)
    action = _definition(
        secured,
        "http",
        method="POST",
        url=f"http://127.0.0.1:{echo}/x",
        headers="Authorization: Bearer ${secret:API_KEY}",
        body="${secret:API_KEY}",
    )
    _use(secured, pipeline, action)
    uses = secured.get("/api/secrets/API_KEY/uses").json()
    assert [(u["node_id"], u["graph_name"], u["kind"]) for u in uses] == [
        (action["node"]["id"], action["name"], "http")
    ]
    assert uses[0]["pipelines"] == [{"id": pipeline["id"], "name": pipeline["name"]}]
    _start(secured, pipeline, task)
    run = _wait(secured, task, "done")
    assert _Echo.hits[0][1]["Authorization"] == f"Bearer {VALUE}"
    result = _work(run)[0]
    assert VALUE not in json.dumps(run) and "***" in result["output"]
    for snapshot in _snapshots(migrated_settings):
        assert VALUE not in snapshot and "${secret:API_KEY}" in snapshot


def test_a_deleted_secret_makes_the_node_fail_and_a_changed_key_makes_it_unreadable(
    secured: TestClient, migrated_settings: Settings
) -> None:
    _put(secured, "API_KEY")
    pipeline, task = _pipeline(secured, stages=1), _make_task(secured)
    action = _definition(
        secured, "code", language="sh", code="echo $API_KEY", secrets="API_KEY", timeout_seconds=5
    )
    _use(secured, pipeline, action)
    assert secured.delete("/api/secrets/API_KEY").status_code == 204
    _start(secured, pipeline, task)
    run = _wait(secured, task, "failed")
    assert _work(run)[0]["reason"] == "Secret API_KEY does not exist"

    _put(secured, "API_KEY")
    store = secured.app.state.secret_store  # type: ignore[attr-defined]
    store._settings = store._settings.model_copy(
        update={"secret_key": "a-different-key-" + "z" * 20}
    )
    task2 = _make_task(secured, "Second")
    _start(secured, pipeline, task2)
    run = _wait(secured, task2, "failed")
    assert _work(run)[0]["reason"] == "Secret API_KEY cannot be read: the secret key changed"


# ── migration ────────────────────────────────────────────────────────


def test_migration_0022_goes_up_down_and_up(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    path = settings.data_dir / settings.database_filename
    cfg = alembic_config()
    command.upgrade(cfg, "0021")
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO secrets (id, name, value, created_at, updated_at) "
            "VALUES ('1', 'A', x'00', '2026-01-01', '2026-01-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):  # the name is unique
            conn.execute(
                "INSERT INTO secrets (id, name, value, created_at, updated_at) "
                "VALUES ('2', 'A', x'00', '2026-01-01', '2026-01-01')"
            )
    command.downgrade(cfg, "0021")
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "secrets" not in tables and "run_node_results" in tables
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM secrets").fetchone() == (0,)
    command.check(cfg)


# ── the store: nothing to resolve, nodes that do not name the secret ─


def test_resolving_no_names_needs_no_database_and_gives_nothing(secured: TestClient) -> None:
    store = secured.app.state.secret_store  # type: ignore[attr-defined]
    assert secured.portal is not None
    assert secured.portal.call(store.resolve, []) == {}
    assert secured.portal.call(store.resolve, ()) == {}


def test_uses_lists_only_nodes_that_name_the_secret_and_skips_a_broken_code_setting(
    secured: TestClient, migrated_settings: Settings
) -> None:
    _put(secured, "API_KEY")
    _put(secured, "OTHER_KEY")
    mentions = _definition(secured, "http", url="https://example.org/?k=${secret:API_KEY}")
    unrelated = _definition(secured, "http", url="https://example.org/?k=${secret:OTHER_KEY}")
    code = _definition(secured, "code", language="sh", code="true", secrets="API_KEY")
    broken = _definition(secured, "code", language="sh", code="true", secrets="API_KEY")
    plain = _definition(secured, "http", url="https://example.org/")
    # a setting the API would refuse, as an old or hand-edited database may hold it
    path = migrated_settings.data_dir / migrated_settings.database_filename
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE graph_nodes SET config = ? WHERE id = ?",
            (
                json.dumps({"language": "sh", "code": "true", "secrets": "not a name!"}),
                broken["node"]["id"],
            ),
        )
    found = secured.get("/api/secrets/API_KEY/uses")
    assert found.status_code == 200
    assert sorted(u["node_id"] for u in found.json()) == sorted(
        [mentions["node"]["id"], code["node"]["id"]]
    )
    other = secured.get("/api/secrets/OTHER_KEY/uses").json()
    assert [u["node_id"] for u in other] == [unrelated["node"]["id"]]
    assert secured.get("/api/secrets/NOBODY_USES_THIS/uses").json() == []
    assert plain["node"]["id"] not in found.text


def test_the_timestamps_of_a_replaced_secret_keep_created_and_move_updated(
    secured: TestClient,
) -> None:
    created = _put(secured, "API_KEY").json()
    replaced = _put(secured, "API_KEY", "another-value-1").json()
    assert replaced["created_at"] == created["created_at"]
    assert replaced["updated_at"] >= created["updated_at"]

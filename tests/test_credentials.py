"""Managed credentials (ADR-051): internal tokens (hash, once, expiry, rotation, revocation, scope), external
credentials (metadata, state, tests, uses) and their compatibility with the secrets and the existing token."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.credentials import tokens
from openartifact.credentials.store import SecretResolveError

TOKEN = "managed-credentials-token-" + "x" * 20
KEY = "k" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
VALUE = "ghp_SuperSecretValue123"


@pytest.fixture
def app_client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    settings = migrated_settings.model_copy(
        update={"api_token": TOKEN, "secret_key": KEY, "http_allow_private_networks": True}
    )
    with TestClient(_create_app(settings), headers=HEADERS) as c:
        yield c


def _db(settings: Settings) -> str:
    return settings.database_url.split("///", 1)[1]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make(
    client: TestClient, type_: str = "api_access_token", name: str = "ci", **extra: Any
) -> dict[str, Any]:
    response = client.post("/api/credentials/internal", json={"type": type_, "name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _anonymous(client: TestClient, token: str, path: str = "/api/v1/secrets") -> int:
    return client.get(path, headers=_bearer(token)).status_code


# ── token primitives ─────────────────────────────────────────────────


def test_a_token_has_a_public_id_and_only_its_hash_matches() -> None:
    token, public_id, digest = tokens.new_token()
    assert token.startswith("oa_") and tokens.public_id_of(token) == public_id
    assert tokens.matches(token, digest) and not tokens.matches(token + "x", digest)
    assert tokens.public_id_of("not-ours") is None and tokens.public_id_of("oa_zz_x") is None


# ── internal lifecycle ───────────────────────────────────────────────


def test_an_internal_token_is_shown_once_stored_as_a_hash_and_opens_the_api(
    app_client: TestClient, migrated_settings: Settings
) -> None:
    made = _make(app_client)
    token = made["token"]
    assert _anonymous(app_client, token) == 200
    assert token not in app_client.get("/api/credentials").text
    assert token not in app_client.get(f"/api/credentials/{made['credential']['id']}").text
    with sqlite3.connect(_db(migrated_settings)) as conn:
        dump = " ".join(str(r) for r in conn.execute("SELECT * FROM internal_tokens"))
        assert token not in dump and tokens.hash_token(token) in dump
    assert (
        app_client.get("/api/credentials/ci").json()["internal"]["tokens"][0]["state"] == "current"
    )


def test_an_mcp_token_does_not_open_the_api_and_an_unknown_one_opens_nothing(
    app_client: TestClient,
) -> None:
    mcp = _make(app_client, "mcp_access_token", "agent")["token"]
    assert _anonymous(app_client, mcp) == 401
    assert _anonymous(app_client, "oa_000000000000_" + "a" * 43) == 401
    assert _anonymous(app_client, "garbage") == 401


def test_a_disabled_token_fails_at_once_and_works_again_when_switched_on(
    app_client: TestClient,
) -> None:
    token = _make(app_client)["token"]
    app_client.put("/api/credentials/ci/enabled", json={"enabled": False})
    assert _anonymous(app_client, token) == 401
    assert app_client.get("/api/credentials/ci").json()["status"] == "disabled"
    app_client.put("/api/credentials/ci/enabled", json={"enabled": True})
    assert _anonymous(app_client, token) == 200


def test_a_revoked_token_fails_for_good_and_cannot_be_switched_on_or_rotated(
    app_client: TestClient,
) -> None:
    token = _make(app_client)["token"]
    assert app_client.post("/api/credentials/ci/revoke").json()["status"] == "revoked"
    assert _anonymous(app_client, token) == 401
    assert app_client.put("/api/credentials/ci/enabled", json={"enabled": True}).status_code == 409
    assert app_client.post("/api/credentials/ci/rotate", json={}).status_code == 409


def test_an_expired_token_fails(app_client: TestClient, migrated_settings: Settings) -> None:
    made = _make(app_client, expires_in_seconds=3600)
    with sqlite3.connect(_db(migrated_settings)) as conn:
        conn.execute("UPDATE internal_credentials SET expires_at = '2000-01-01 00:00:00'")
    assert _anonymous(app_client, made["token"]) == 401
    assert app_client.get("/api/credentials/ci").json()["status"] == "expired"


def test_rotation_keeps_the_old_token_for_the_grace_period_then_ends_it(
    app_client: TestClient, migrated_settings: Settings
) -> None:
    old = _make(app_client)["token"]
    rotated = app_client.post("/api/credentials/ci/rotate", json={"grace_seconds": 3600}).json()
    new = rotated["token"]
    assert new != old and _anonymous(app_client, new) == 200 and _anonymous(app_client, old) == 200
    states = {t["state"] for t in rotated["credential"]["internal"]["tokens"]}
    assert states == {"current", "grace"}
    with sqlite3.connect(_db(migrated_settings)) as conn:
        conn.execute(
            "UPDATE internal_tokens SET valid_until = '2000-01-01 00:00:00' WHERE valid_until IS NOT NULL"
        )
    assert _anonymous(app_client, old) == 401 and _anonymous(app_client, new) == 200


def test_rotation_with_no_grace_ends_the_old_token_at_once(app_client: TestClient) -> None:
    old = _make(app_client)["token"]
    new = app_client.post("/api/credentials/ci/rotate", json={"grace_seconds": 0}).json()["token"]
    time.sleep(0.01)
    assert _anonymous(app_client, old) == 401 and _anonymous(app_client, new) == 200


def test_credentials_are_revoked_independently(app_client: TestClient) -> None:
    a, b = _make(app_client, name="a")["token"], _make(app_client, name="b")["token"]
    app_client.post("/api/credentials/a/revoke")
    assert _anonymous(app_client, a) == 401 and _anonymous(app_client, b) == 200


def test_the_environment_token_keeps_working_after_everything_is_revoked(
    app_client: TestClient,
) -> None:
    _make(app_client)
    app_client.post("/api/credentials/ci/revoke")
    assert (
        app_client.get("/api/v1/secrets").status_code == 200
    )  # the client's own header is the env token


def test_a_name_is_unique_ignoring_case(app_client: TestClient) -> None:
    _make(app_client, name="CI")
    again = app_client.post(
        "/api/credentials/internal", json={"type": "api_access_token", "name": "ci"}
    )
    assert again.status_code == 409


def test_an_internal_token_needs_the_api_token_to_be_configured_and_a_known_type(
    app_client: TestClient,
) -> None:
    bad = app_client.post("/api/credentials/internal", json={"type": "github_pat", "name": "x"})
    assert bad.status_code == 422


def test_an_internal_credential_is_never_a_secret(app_client: TestClient) -> None:
    _make(app_client)
    assert [s["name"] for s in app_client.get("/api/secrets").json()] == []
    assert "ci" not in app_client.get("/api/credentials?category=external").text


def test_the_audit_trail_records_what_happened_without_a_token(app_client: TestClient) -> None:
    token = _make(app_client)["token"]
    app_client.post("/api/credentials/ci/rotate", json={})
    app_client.post("/api/credentials/ci/revoke")
    events = app_client.get("/api/credentials/ci/events").json()
    assert {e["action"] for e in events} == {"created", "rotated", "revoked"}
    assert token not in str(events)


def test_a_token_never_reaches_the_logs(
    app_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        token = _make(app_client)["token"]
        _anonymous(app_client, token)
    assert token not in caplog.text


# ── external ─────────────────────────────────────────────────────────


def _store(client: TestClient, name: str = "GITHUB_TOKEN", type_: str = "github_pat") -> Any:
    return client.post(
        "/api/credentials/external",
        json={"type": type_, "name": name, "description": "d", "fields": {"value": VALUE}},
    )


def test_an_external_credential_keeps_its_value_in_the_secret_store_and_never_returns_it(
    app_client: TestClient,
) -> None:
    made = _store(app_client)
    assert made.status_code == 201 and VALUE not in made.text
    assert VALUE not in app_client.get("/api/credentials").text
    assert [s["name"] for s in app_client.get("/api/secrets").json()] == ["GITHUB_TOKEN"]
    body = made.json()
    assert body["external"]["last_test_ok"] is None and body["status"] == "active"


def test_a_secret_made_with_the_older_api_appears_as_a_generic_credential_and_back(
    app_client: TestClient,
) -> None:
    app_client.put("/api/secrets/LEGACY", json={"value": VALUE})
    listed = {c["name"]: c for c in app_client.get("/api/credentials").json()}
    assert (
        listed["LEGACY"]["type"] == "generic_api_key" and listed["LEGACY"]["category"] == "external"
    )
    app_client.delete("/api/secrets/LEGACY")
    assert app_client.get("/api/credentials/LEGACY").status_code == 404


def test_invalid_fields_are_refused_with_the_reason(app_client: TestClient) -> None:
    r = app_client.post(
        "/api/credentials/external",
        json={"type": "postgres_connection", "name": "DB", "fields": {"value": "mysql://x"}},
    )
    assert r.status_code == 422 and "postgresql://" in r.text
    r = app_client.post(
        "/api/credentials/external", json={"type": "github_pat", "name": "GH", "fields": {}}
    )
    assert r.status_code == 422 and "a value is needed" in r.text
    r = app_client.post(
        "/api/credentials/external",
        json={"type": "github_pat", "name": "gh", "fields": {"value": "x"}},
    )
    assert r.status_code == 422  # a name is what ${secret:NAME} says
    r = app_client.post(
        "/api/credentials/external",
        json={"type": "github_pat", "name": "GH", "fields": {"value": "x", "evil": "y"}},
    )
    assert r.status_code == 422 and "evil" in r.text


def test_update_changes_description_and_value_and_makes_the_test_stale(
    app_client: TestClient,
) -> None:
    _store(app_client, "API_KEY", "generic_api_key")
    changed = app_client.patch(
        "/api/credentials/API_KEY", json={"description": "new", "fields": {"value": "other"}}
    ).json()
    assert changed["description"] == "new"
    kept = app_client.patch("/api/credentials/API_KEY", json={"fields": {"value": ""}})
    assert kept.status_code == 200


def test_a_type_without_a_test_is_never_reported_as_tested(app_client: TestClient) -> None:
    _store(app_client, "API_KEY", "generic_api_key")
    r = app_client.post("/api/credentials/API_KEY/test")
    assert r.status_code == 422 and "no connection test" in r.text
    assert app_client.get("/api/credentials/API_KEY").json()["external"]["last_test_at"] is None


def test_a_failed_test_is_recorded_with_its_time_and_without_the_value(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openartifact.credentials import testing

    async def refused(
        value: str, settings: dict[str, Any], allow_private: bool
    ) -> tuple[bool, str]:
        return False, "GitHub refused the token (HTTP 401)"

    monkeypatch.setitem(testing.TESTERS, "github_pat", refused)
    _store(app_client)
    body = app_client.post("/api/credentials/GITHUB_TOKEN/test").json()["external"]
    assert body["last_test_ok"] is False and body["last_test_at"] and VALUE not in str(body)
    monkeypatch.setitem(testing.TESTERS, "github_pat", lambda *a: _ok())
    assert (
        app_client.post("/api/credentials/GITHUB_TOKEN/test").json()["external"]["last_test_ok"]
        is True
    )
    app_client.patch("/api/credentials/GITHUB_TOKEN", json={"fields": {"value": "new"}})
    assert (
        app_client.get("/api/credentials/GITHUB_TOKEN").json()["external"]["last_test_at"] is None
    )


async def _ok() -> tuple[bool, str]:
    return True, "fine"


def test_a_disabled_external_credential_is_not_handed_out(app_client: TestClient) -> None:
    import asyncio

    _store(app_client)
    store = app_client.app.state.secret_store  # type: ignore[attr-defined]
    assert asyncio.run(store.resolve(["GITHUB_TOKEN"])) == {"GITHUB_TOKEN": VALUE}
    app_client.put("/api/credentials/GITHUB_TOKEN/enabled", json={"enabled": False})
    with pytest.raises(SecretResolveError, match="switched off"):
        asyncio.run(store.resolve(["GITHUB_TOKEN"]))
    app_client.put("/api/credentials/GITHUB_TOKEN/enabled", json={"enabled": True})
    assert asyncio.run(store.resolve(["GITHUB_TOKEN"])) == {"GITHUB_TOKEN": VALUE}


def test_an_internal_credential_cannot_be_resolved_as_a_secret(app_client: TestClient) -> None:
    import asyncio

    _make(app_client, name="ci")
    store = app_client.app.state.secret_store  # type: ignore[attr-defined]
    with pytest.raises(SecretResolveError, match="does not exist"):
        asyncio.run(store.resolve(["ci"]))


def test_delete_removes_the_value_and_keeps_the_history(app_client: TestClient) -> None:
    made = _store(app_client).json()
    assert app_client.delete("/api/credentials/GITHUB_TOKEN").status_code == 204
    assert app_client.get("/api/secrets").json() == []
    assert app_client.get("/api/credentials/GITHUB_TOKEN").status_code == 404
    assert made["id"]


def test_uses_lists_nodes_and_providers_that_refer_to_a_credential(app_client: TestClient) -> None:
    _store(app_client, "API_KEY", "generic_api_key")
    assert app_client.get("/api/credentials/API_KEY/uses").json() == []


def test_the_types_say_what_is_testable_and_what_fields_they_have(app_client: TestClient) -> None:
    types = {t["id"]: t for t in app_client.get("/api/credentials/types").json()}
    assert types["github_pat"]["testable"] is True and types["bearer_token"]["testable"] is False
    assert types["api_access_token"]["category"] == "internal"


def test_the_management_api_needs_the_token(app_client: TestClient) -> None:
    anonymous = TestClient(app_client.app)
    assert anonymous.get("/api/credentials").status_code == 401
    assert (
        anonymous.post(
            "/api/credentials/internal", json={"type": "api_access_token", "name": "x"}
        ).status_code
        == 401
    )
    managed = _make(app_client)["token"]
    assert anonymous.get("/api/credentials", headers=_bearer(managed)).status_code == 200


def test_an_mcp_token_opens_the_mcp_server_and_a_revoked_one_does_not(
    app_client: TestClient,
) -> None:
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    }
    accept = {"Accept": "application/json, text/event-stream"}

    def status(token: str) -> int:
        return (
            TestClient(app_client.app)
            .post("/mcp", json=init, headers={**_bearer(token), **accept})
            .status_code
        )

    mcp = _make(app_client, "mcp_access_token", "agent")["token"]
    api = _make(app_client, "api_access_token", "ci")["token"]
    assert status(mcp) == 200 and status(api) == 200  # an API token opens both
    assert status("oa_000000000000_nope") == 401
    app_client.post("/api/credentials/agent/revoke")
    assert status(mcp) == 401

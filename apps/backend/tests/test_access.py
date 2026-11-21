"""Access protection: with an API token the whole application needs it (header or sign-in)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings

TOKEN = "t0ken-for-the-tests"
HTML = {"Accept": "text/html"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def secured(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """The application with an API token configured."""
    settings = migrated_settings.model_copy(update={"api_token": TOKEN, "secret_key": "k" * 40})
    with TestClient(_create_app(settings)) as c:
        yield c


def test_without_a_token_the_application_is_open_but_the_integration_api_is_closed(
    client: TestClient,
) -> None:
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/", headers=HTML).status_code == 200
    assert client.get("/login", follow_redirects=False).headers["location"] == "/"
    assert client.get("/api/v1/artifacts").status_code == 401  # nothing to compare a token with
    assert client.post("/mcp", json={}).status_code == 401


def test_a_page_without_the_token_leads_to_the_sign_in(secured: TestClient) -> None:
    response = secured.get("/pipelines?x=1", headers=HTML, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fpipelines%3Fx%3D1"


def test_api_swagger_and_the_openapi_document_are_closed_without_the_token(
    secured: TestClient,
) -> None:
    for path in (
        "/api/tasks",
        "/api/pipelines",
        "/api/actions",
        "/api/events",
        "/api/info",
        "/openapi.json",
    ):
        response = secured.get(path, follow_redirects=False)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
    assert secured.delete("/api/pipelines/x").status_code == 401  # writes too
    assert secured.get("/api/docs", headers=HTML, follow_redirects=False).status_code == 303


def test_health_the_sign_in_page_and_static_files_stay_open(secured: TestClient) -> None:
    assert secured.get("/health").status_code == 200
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/login").status_code == 200
    assert secured.get("/static/css/tokens.css").status_code == 200


def test_the_bearer_token_opens_everything(secured: TestClient) -> None:
    assert secured.get("/api/tasks", headers=BEARER).status_code == 200
    assert secured.get("/openapi.json", headers=BEARER).status_code == 200
    assert secured.get("/api/v1/artifacts", headers=BEARER).status_code == 200
    assert secured.get("/api/tasks", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_signing_in_sets_a_session_cookie_and_signing_out_removes_it(secured: TestClient) -> None:
    wrong = secured.post("/login", data={"token": "nope", "next": "/"}, follow_redirects=False)
    assert wrong.status_code == 401
    assert "oa_session" not in wrong.headers.get("set-cookie", "")
    assert "not right" in wrong.text

    ok = secured.post("/login", data={"token": TOKEN, "next": "/pipelines"}, follow_redirects=False)
    assert (ok.status_code, ok.headers["location"]) == (303, "/pipelines")
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert (
        TOKEN not in ok.headers["set-cookie"]
    )  # the cookie is derived from the token, not the token

    assert secured.get("/", headers=HTML, follow_redirects=False).status_code == 200
    assert secured.get("/api/tasks").status_code == 200
    assert "Sign out" in secured.get("/", headers=HTML).text

    secured.post("/logout", follow_redirects=False)
    secured.cookies.clear()
    assert secured.get("/api/tasks").status_code == 401


@pytest.mark.parametrize("target", ["//evil.example", "https://evil.example", "/\\evil", ""])
def test_sign_in_goes_only_to_pages_of_this_application(secured: TestClient, target: str) -> None:
    response = secured.post("/login", data={"token": TOKEN, "next": target}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_a_forged_cookie_does_not_open_anything(secured: TestClient) -> None:
    secured.cookies.set("oa_session", "0" * 64)
    assert secured.get("/api/tasks").status_code == 401


def test_the_mcp_server_accepts_the_bearer_token_behind_the_gate(secured: TestClient) -> None:
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    headers = {**BEARER, "Accept": "application/json, text/event-stream"}
    assert secured.post("/mcp", json=init).status_code == 401
    assert secured.post("/mcp", json=init, headers=headers).status_code == 200

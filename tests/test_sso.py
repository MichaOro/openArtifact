"""Single sign-on through OpenID Connect (ADR-043): the sign-in page, the code flow with PKCE, the checks of
the ID token, the list of who may come in, and what a refusal leaves behind (no session).

A fake provider (``oidc_support``) issues the tokens, so every refusal is checked against a real, signed
token that is wrong in exactly one way.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Generator, Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.oidc_support import CLIENT_ID, CLIENT_SECRET, FakeIdp, fake_idp

TOKEN = "sso-test-api-token-" + "x" * 20
KEY = "k" * 40
Make = Callable[..., TestClient]


@pytest.fixture
def idp() -> Iterator[FakeIdp]:
    with fake_idp() as server:
        yield server


@pytest.fixture
def make(migrated_settings: Settings, idp: FakeIdp) -> Generator[Make, None, None]:
    clients: list[TestClient] = []

    def build(**overrides: Any) -> TestClient:
        settings = migrated_settings.model_copy(
            update={
                "api_token": TOKEN,
                "secret_key": KEY,
                "oidc_issuer": idp.issuer,
                "oidc_client_id": CLIENT_ID,
                "oidc_client_secret": CLIENT_SECRET,
                "oidc_allowed_emails": "owner@example.org",
                **overrides,
            }
        )
        client = TestClient(_create_app(settings), follow_redirects=False)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def _begin(client: TestClient, target: str = "/") -> dict[str, str]:
    """Start the sign-in: the parameters the application sent the browser to the provider with."""
    response = client.get("/login/sso", params={"next": target})
    assert response.status_code == 303, response.text
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def _finish(client: TestClient, params: dict[str, str], **query: str) -> Any:
    return client.get(
        "/login/sso/callback", params={"code": "the-code", "state": params["state"], **query}
    )


def _signed_in(client: TestClient) -> bool:
    return client.get("/api/providers").status_code == 200


# ── the sign-in page ─────────────────────────────────────────────────


def test_the_sign_in_page_offers_sso_only_when_it_is_configured(make: Make) -> None:
    on = make(oidc_button_label="Sign in with Authelia").get("/login")
    assert "Sign in with Authelia" in on.text and 'href="/login/sso' in on.text
    off = make(oidc_issuer="", oidc_client_id="", oidc_client_secret="").get("/login")
    assert "/login/sso" not in off.text and "API token" in off.text  # the token form stays


def test_the_sso_routes_do_not_exist_when_it_is_not_configured(make: Make) -> None:
    client = make(oidc_issuer="", oidc_client_id="", oidc_client_secret="")
    assert client.get("/login/sso").status_code == 404
    assert client.get("/login/sso/callback", params={"code": "c", "state": "s"}).status_code == 404


# ── the code flow ────────────────────────────────────────────────────


def test_the_browser_is_sent_to_the_provider_with_state_nonce_and_a_pkce_challenge(
    make: Make, idp: FakeIdp
) -> None:
    client = make()
    response = client.get("/login/sso", params={"next": "/executions"})
    target = urlsplit(response.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{idp.issuer}/authorize"
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == "http://testserver/login/sso/callback"
    assert set(query["scope"].split()) >= {"openid", "email"}
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) >= 43
    assert len(query["state"]) >= 16 and len(query["nonce"]) >= 16
    assert "client_secret" not in query
    cookie = response.headers["set-cookie"]
    assert (
        "oa_sso=" in cookie
        and "HttpOnly" in cookie
        and "SameSite=lax" in cookie.replace("Lax", "lax")
    )
    assert "Max-Age=600" in cookie


def test_a_good_sign_in_sets_the_session_and_goes_on_where_the_user_wanted(
    make: Make, idp: FakeIdp
) -> None:
    client = make()
    assert not _signed_in(client)
    params = _begin(client, "/executions?x=1")
    idp.prepare(params["nonce"])
    response = _finish(client, params)
    assert response.status_code == 303 and response.headers["location"] == "/executions?x=1"
    assert "oa_session=" in "".join(response.headers.get_list("set-cookie"))
    assert _signed_in(client)


def test_the_code_is_exchanged_with_the_verifier_and_the_client_secret_only_there(
    make: Make, idp: FakeIdp
) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"])
    _finish(client, params)
    [hit] = idp.token_hits
    form = hit["form"]
    assert form["grant_type"] == "authorization_code" and form["code"] == "the-code"
    assert form["redirect_uri"] == "http://testserver/login/sso/callback"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
    assert challenge.rstrip(b"=").decode() == params["code_challenge"]  # the verifier belongs to it
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert hit["authorization"] == f"Basic {basic}"
    assert "client_secret" not in form  # basic authentication: the secret is not in the body, too


def test_the_state_cookie_is_used_once(make: Make, idp: FakeIdp) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"])
    assert _finish(client, params).status_code == 303
    client.cookies.delete("oa_session")  # a replayed callback must not sign in again
    replay = _finish(client, params)
    assert replay.status_code == 401 and not _signed_in(client)
    assert len(idp.token_hits) == 1  # nothing was sent to the provider for the replay


# ── who may come in ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("setting", "claim"),
    [
        ({"oidc_allowed_emails": "Other@example.org, OWNER@example.org"}, {}),
        ({"oidc_allowed_users": "owner"}, {}),
        ({"oidc_allowed_users": "user-1"}, {"preferred_username": None}),  # the subject
        ({"oidc_allowed_groups": "ops, admins"}, {}),
    ],
)
def test_the_list_names_an_email_a_user_or_a_group(
    make: Make, idp: FakeIdp, setting: dict[str, str], claim: dict[str, Any]
) -> None:
    client = make(**{"oidc_allowed_emails": "", **setting})
    params = _begin(client)
    idp.prepare(params["nonce"], **claim)
    assert _finish(client, params).status_code == 303 and _signed_in(client)


@pytest.mark.parametrize(
    "claim",
    [
        {"email": "intruder@example.org"},
        {
            "email": "owner@example.org",
            "email_verified": False,
        },  # an unverified address proves nothing
        {"email": None},
    ],
)
def test_someone_who_is_not_on_the_list_gets_no_session(
    make: Make, idp: FakeIdp, claim: dict[str, Any]
) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"], **claim)
    response = _finish(client, params)
    assert response.status_code == 403 and "not allowed" in response.text
    assert not _signed_in(client) and "oa_session" not in response.headers.get("set-cookie", "")


def test_a_group_of_someone_else_does_not_let_a_user_in(make: Make, idp: FakeIdp) -> None:
    client = make(oidc_allowed_emails="", oidc_allowed_groups="ops")
    params = _begin(client)
    idp.prepare(params["nonce"], groups=["admins"])
    assert _finish(client, params).status_code == 403


def test_claims_the_id_token_lacks_are_read_from_userinfo(make: Make, idp: FakeIdp) -> None:
    client = make(oidc_allowed_emails="", oidc_allowed_groups="admins")
    params = _begin(client)
    idp.prepare(params["nonce"], groups=None, email=None, preferred_username=None)
    idp.userinfo = {"sub": "user-1", "groups": ["admins"], "email": "owner@example.org"}
    assert _finish(client, params).status_code == 303 and _signed_in(client)
    assert idp.userinfo_hits == [f"Bearer {idp.access_token}"]


def test_userinfo_of_another_subject_is_refused(make: Make, idp: FakeIdp) -> None:
    client = make(oidc_allowed_emails="", oidc_allowed_groups="admins")
    params = _begin(client)
    idp.prepare(params["nonce"], groups=None, email=None, preferred_username=None)
    idp.userinfo = {"sub": "someone-else", "groups": ["admins"]}
    assert _finish(client, params).status_code == 403 and not _signed_in(client)


# ── the checks of the ID token ───────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("another audience", {"aud": "someone-else"}),
        ("another issuer", {"iss": "https://evil.example"}),
        ("expired", {"exp": 1_000_000_000}),
        ("without an expiry", {"exp": None}),
        ("another nonce", {"nonce": "not-the-one"}),
        ("without a nonce", {"nonce": None}),
    ],
)
def test_an_id_token_that_is_wrong_in_one_claim_is_refused(
    make: Make, idp: FakeIdp, name: str, changes: dict[str, Any]
) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"], **changes)
    response = _finish(client, params)
    assert response.status_code == 401, name
    assert not _signed_in(client)


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_a_token_with_a_forbidden_algorithm_is_refused(
    make: Make, idp: FakeIdp, algorithm: str
) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"], algorithm=algorithm)
    assert _finish(client, params).status_code == 401 and not _signed_in(client)


def test_a_token_signed_by_a_stranger_is_refused(make: Make, idp: FakeIdp) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"], key=idp.stranger)
    assert _finish(client, params).status_code == 401 and not _signed_in(client)


# ── what the browser sends back ──────────────────────────────────────


def test_a_callback_with_another_state_is_refused_before_anything_is_sent(
    make: Make, idp: FakeIdp
) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"])
    response = client.get("/login/sso/callback", params={"code": "c", "state": "forged"})
    assert response.status_code == 401 and idp.token_hits == [] and not _signed_in(client)


def test_a_callback_without_the_state_cookie_is_refused(make: Make, idp: FakeIdp) -> None:
    """Someone else's code arriving at this browser (login CSRF): no cookie, no sign-in."""
    started = make()
    params = _begin(started)
    idp.prepare(params["nonce"])
    other = make()
    assert _finish(other, params).status_code == 401 and idp.token_hits == []


def test_the_provider_may_refuse_and_its_message_is_not_trusted_as_html(
    make: Make, idp: FakeIdp
) -> None:
    client = make()
    params = _begin(client)
    response = client.get(
        "/login/sso/callback",
        params={
            "error": "access_denied",
            "error_description": "<script>x</script>",
            "state": params["state"],
        },
    )
    assert response.status_code == 401 and "<script>x" not in response.text
    assert idp.token_hits == [] and not _signed_in(client)


def test_a_token_endpoint_that_refuses_the_code_gives_no_session(make: Make, idp: FakeIdp) -> None:
    client = make()
    params = _begin(client)
    idp.prepare(params["nonce"])
    idp.token_status = 400
    assert _finish(client, params).status_code == 401 and not _signed_in(client)


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example"])
def test_after_the_sign_in_only_a_path_of_the_application_is_a_target(
    make: Make, idp: FakeIdp, target: str
) -> None:
    client = make()
    params = _begin(client, target)
    idp.prepare(params["nonce"])
    assert _finish(client, params).headers["location"] == "/"


# ── the provider's own document ──────────────────────────────────────


def test_a_token_endpoint_on_another_origin_is_refused_and_gets_no_secret(
    make: Make, idp: FakeIdp
) -> None:
    """The discovery document is the provider's word: it may not send the client secret elsewhere."""
    idp.discovery_changes = {"token_endpoint": "http://127.0.0.1:9/token"}
    client = make()
    response = client.get("/login/sso", params={"next": "/"})
    assert response.status_code == 502 and "set-cookie" not in response.headers
    assert not _signed_in(client)


def test_a_discovery_document_for_another_issuer_is_refused(make: Make, idp: FakeIdp) -> None:
    idp.discovery_changes = {"issuer": "https://evil.example"}
    client = make()
    response = client.get("/login/sso", params={"next": "/"})
    assert response.status_code == 502 and "set-cookie" not in response.headers


# ── the settings ─────────────────────────────────────────────────────


def test_sso_without_a_list_of_who_may_come_in_stops_the_start(migrated_settings: Settings) -> None:
    base = migrated_settings.model_copy(
        update={
            "api_token": TOKEN,
            "secret_key": KEY,
            "oidc_issuer": "https://auth.example.org",
            "oidc_client_id": CLIENT_ID,
            "oidc_client_secret": CLIENT_SECRET,
        }
    )
    assert any("OIDC_ALLOWED" in p for p in base.security_problems())
    allowed = base.model_copy(update={"oidc_allowed_groups": "admins"})
    assert not [p for p in allowed.security_problems() if "OIDC" in p]


def test_sso_needs_the_api_token_because_that_is_what_closes_the_application(
    migrated_settings: Settings,
) -> None:
    settings = migrated_settings.model_copy(
        update={
            "api_token": "",
            "oidc_issuer": "https://auth.example.org",
            "oidc_client_id": CLIENT_ID,
            "oidc_client_secret": CLIENT_SECRET,
            "oidc_allowed_groups": "admins",
        }
    )
    assert any("OPENARTIFACT_API_TOKEN" in p and "OIDC" in p for p in settings.security_problems())


@pytest.mark.parametrize("missing", ["oidc_client_id", "oidc_client_secret"])
def test_a_half_configured_sso_stops_the_start(migrated_settings: Settings, missing: str) -> None:
    update = {
        "api_token": TOKEN,
        "secret_key": KEY,
        "oidc_issuer": "https://auth.example.org",
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "oidc_allowed_groups": "admins",
        missing: "",
    }
    problems = migrated_settings.model_copy(update=update).security_problems()
    assert any(missing.upper().replace("OIDC_", "OPENARTIFACT_OIDC_") in p for p in problems)

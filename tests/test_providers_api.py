"""LLM providers through the API: the connection test, models, the two permissions for private networks,
references, the three ways in."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.agents import client as llm_client
from openartifact.agents import providers as providers_module
from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.engine import http_runner
from openartifact.exceptions import ArtifactError
from tests.agent_support import (
    API_KEY,
    HEADERS,
    SECURE,
    FakeLlm,
    completion,
    fake_llm,
    make_agent,
    make_provider,
    put_secret,
)
from tests.helpers import node as _node
from tests.helpers import post as _post

Make = Callable[..., TestClient]


@pytest.fixture
def make_api(migrated_settings: Settings) -> Generator[Make, None, None]:
    stack: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        settings = migrated_settings.model_copy(update={**SECURE, **overrides})
        client = TestClient(_create_app(settings))
        client.__enter__()
        client.headers.update(HEADERS)
        stack.append(client)
        return client

    yield make
    for client in stack:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_api: Make) -> TestClient:
    return make_api()


@pytest.fixture
def llm() -> Iterator[FakeLlm]:
    with fake_llm() as server:
        yield server


def _body(llm: FakeLlm, mount: str = "", **changes: Any) -> dict[str, Any]:
    return {
        "kind": "openai_compatible",
        "name": "Local",
        "base_url": llm.url(mount),
        "secret_name": "LLM_KEY",
        "allow_http": True,
        **changes,
    }


def _steps(result: dict[str, Any]) -> list[tuple[str, bool]]:
    return [(s["name"], s["ok"]) for s in result["steps"]]


# ── creating a custom provider ───────────────────────────────────────


def test_a_provider_with_a_model_list_is_tested_and_saved_with_its_models(
    api: TestClient, llm: FakeLlm
) -> None:
    put_secret(api)
    response = api.post("/api/providers", json=_body(llm, default_model="small", is_default=True))
    assert response.status_code == 201, response.text
    provider = response.json()
    assert (provider["kind"], provider["name"], provider["base_url"]) == (
        "openai_compatible",
        "Local",
        llm.url(),
    )
    assert (provider["secret_name"], provider["secret_exists"]) == ("LLM_KEY", True)
    assert provider["allow_http"] is True and "private_effective" not in provider
    assert provider["check_ok"] is True and provider["checked_at"]
    assert provider["check_message"] == "/models lists 2 models in the OpenAI format"
    models = {m["model_id"]: m for m in provider["models"]}
    assert models["small"] == {
        **models["small"],
        "label": "Small model",
        "source": "fetched",
        "enabled": True,
        "available": True,
    }
    assert (
        models["large"]["enabled"] is False
    )  # fetched models start switched off; the default is switched on
    assert provider["warnings"] == [providers_module.HTTP_WARNING]
    assert API_KEY not in json.dumps(provider)
    assert llm.hits[0]["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert api.get(f"/api/providers/{provider['id']}").json() == provider
    assert api.get("/api/providers/local").json()["id"] == provider["id"]
    assert [p["id"] for p in api.get("/api/providers").json()] == [provider["id"]]


def test_the_test_alone_saves_nothing_and_lists_its_steps(api: TestClient, llm: FakeLlm) -> None:
    put_secret(api)
    result = api.post("/api/providers/test", json=_body(llm)).json()
    assert (
        result["ok"] is True
        and result["lists_models"] is True
        and result["models"] == ["small", "large"]
    )
    assert _steps(result) == [("secret", True), ("models", True)]
    assert result["warnings"] == [providers_module.HTTP_WARNING]
    assert api.get("/api/providers").json() == []


def test_an_endpoint_without_a_model_list_needs_a_model_and_one_probe_completion(
    api: TestClient, llm: FakeLlm
) -> None:
    put_secret(api)
    without = api.post("/api/providers/test", json=_body(llm, "/nomodels")).json()
    assert without["ok"] is False and _steps(without) == [
        ("secret", True),
        ("models", True),
        ("completion", False),
    ]
    assert without["steps"][2]["message"] == (
        "The endpoint lists no models: define a model by hand, it is used for the test"
    )
    assert api.post("/api/providers", json=_body(llm, "/nomodels")).status_code == 422
    llm.hits.clear()
    body = _body(
        llm,
        "/nomodels",
        models=[{"model_id": "my-model", "label": "Mine"}],
        default_model="my-model",
    )
    response = api.post("/api/providers", json=body)
    assert response.status_code == 201, response.text
    probe = llm.completions()[0]["json"]
    assert probe == {
        "model": "my-model",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "max_tokens": 1,
    }
    provider = response.json()
    assert provider["check_message"].startswith(
        'A minimal chat completion with model "my-model" was answered'
    )
    assert provider["models"] == [
        {
            "id": provider["models"][0]["id"],
            "model_id": "my-model",
            "label": "Mine",
            "source": "manual",
            "enabled": True,
            "available": True,
        }
    ]


@pytest.mark.parametrize(
    ("script", "message"),
    [
        (
            (200, b"<html>hello</html>"),
            "The answer is not an OpenAI-compatible chat completion (no choices)",
        ),
        (
            (200, {"ok": True}),
            "The answer is not an OpenAI-compatible chat completion (no choices)",
        ),
        (
            (404, {"error": {"message": "model not found"}}),
            "HTTP 404: not found (check the address and the model): model not found",
        ),
        (
            (401, {"error": {"message": "bad key"}}),
            "HTTP 401: the provider did not accept the API key: bad key",
        ),
    ],
)
def test_a_success_status_alone_is_not_enough_for_the_probe(
    api: TestClient, llm: FakeLlm, script: tuple[Any, ...], message: str
) -> None:
    put_secret(api)
    llm.script = [script]
    body = _body(llm, "/nomodels", models=[{"model_id": "my-model"}])
    refused = api.post("/api/providers", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"] == f'The connection test failed: Model "my-model": {message}'
    assert api.get("/api/providers").json() == []


def test_an_endpoint_that_answers_with_a_web_page_is_refused(api: TestClient, llm: FakeLlm) -> None:
    put_secret(api)
    # /models is a page (not a model list), so a model is probed: the page is no chat completion either
    result = api.post(
        "/api/providers/test", json=_body(llm, "/html", models=[{"model_id": "m"}])
    ).json()
    assert result["ok"] is False and _steps(result)[-1] == ("completion", False)
    assert (
        api.post("/api/providers", json=_body(llm, "/html", models=[{"model_id": "m"}])).status_code
        == 422
    )


def test_a_refused_key_fails_the_test(api: TestClient, llm: FakeLlm) -> None:
    put_secret(api)
    result = api.post("/api/providers/test", json=_body(llm, "/denied")).json()
    assert result["ok"] is False
    assert result["steps"][-1] == {
        "name": "models",
        "ok": False,
        "message": "HTTP 401: the provider did not accept the API key: Invalid API key",
    }


def test_a_secret_that_does_not_exist_fails_the_test_before_any_request(
    api: TestClient, llm: FakeLlm
) -> None:
    result = api.post("/api/providers/test", json=_body(llm)).json()
    assert result["ok"] is False and result["steps"] == [
        {"name": "secret", "ok": False, "message": "Secret LLM_KEY does not exist"}
    ]
    assert llm.hits == []
    refused = api.post("/api/providers", json=_body(llm))
    assert refused.json()["detail"] == "The connection test failed: Secret LLM_KEY does not exist"


def test_a_provider_without_a_key_sends_none(api: TestClient, llm: FakeLlm) -> None:
    provider = api.post("/api/providers", json=_body(llm, secret_name=None)).json()
    assert provider["secret_name"] is None and provider["secret_exists"] is False
    assert "authorization" not in llm.hits[0]["headers"]


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"base_url": None}, "The address must be an http or https URL with a host"),
        ({"base_url": "ftp://x/v1"}, "The address must be an http or https URL with a host"),
        ({"base_url": "http://"}, "The address must be an http or https URL with a host"),
        ({"base_url": "http://[::1"}, "The address must be an http or https URL with a host"),
        (
            {"base_url": "https://user:pw@llm.example/v1"},
            "The address must not contain a user name or password",
        ),
        (
            {"base_url": "https://llm.example/v1?key=1"},
            "The address must not have a query or a fragment",
        ),
        (
            {"secret_name": "lower"},
            "A secret name has capitals, digits and underscores and starts with a letter",
        ),
    ],
)
def test_an_address_or_secret_name_that_cannot_be_used_is_refused_before_the_test(
    api: TestClient, llm: FakeLlm, change: dict[str, Any], detail: str
) -> None:
    for path in ("/api/providers", "/api/providers/test"):
        refused = api.post(path, json=_body(llm, **change))
        assert refused.status_code == 422 and refused.json()["detail"] == detail
    assert llm.hits == []


def test_names_are_unique_and_the_default_model_must_be_a_model(
    api: TestClient, llm: FakeLlm
) -> None:
    make_provider(api, llm)
    assert api.post("/api/providers", json=_body(llm, name="LOCAL")).status_code == 409
    refused = api.post("/api/providers", json=_body(llm, name="Second", default_model="nope"))
    assert (
        refused.status_code == 422
        and refused.json()["detail"] == 'The default model "nope" is not a model of the provider'
    )
    assert api.post("/api/providers", json=_body(llm, name="  ")).status_code == 422
    assert api.post("/api/providers", json={**_body(llm), "extra": 1}).status_code == 422


# ── the address: any address, http only when it is ticked ─────────────


def test_a_local_address_needs_no_permission_of_the_operator(make_api: Make, llm: FakeLlm) -> None:
    """The address of a provider is just an address: a local one works without the operator's switch."""
    closed = make_api(llm_allow_private_networks=False)
    put_secret(closed)
    response = closed.post("/api/providers", json=_body(llm))
    assert response.status_code == 201, response.text
    assert response.json()["check_ok"] is True and llm.hits


def test_an_http_address_needs_the_tick_for_unencrypted_connections(
    api: TestClient, llm: FakeLlm
) -> None:
    put_secret(api)
    refused = api.post("/api/providers", json=_body(llm, allow_http=False))
    assert refused.status_code == 422
    assert refused.json()["detail"] == llm_client.UNENCRYPTED_REFUSED
    tested = api.post("/api/providers/test", json=_body(llm, allow_http=False))
    assert tested.status_code == 422  # the test refuses it before any request, too
    assert llm.hits == []


def test_https_needs_no_tick() -> None:
    providers_module.check_encryption("https://llm.example/v1", False)
    providers_module.check_encryption("http://10.0.0.5/v1", True)
    with pytest.raises(ArtifactError, match="unencrypted"):
        providers_module.check_encryption("http://10.0.0.5/v1", False)


def test_the_permission_for_providers_does_not_open_http_nodes(api: TestClient) -> None:
    limits = api.app.state.engine._limits  # type: ignore[attr-defined]
    assert limits.llm_allow_private_networks is True and limits.http_allow_private_networks is False


def test_a_metadata_address_is_refused_with_both_permissions(api: TestClient) -> None:
    body = {
        "kind": "openai_compatible",
        "name": "Meta",
        "base_url": "http://169.254.169.254/v1",
        "allow_http": True,
    }
    result = api.post("/api/providers/test", json=body).json()
    assert result["ok"] is False
    assert result["steps"][-1]["message"] == "The address is not allowed (cloud metadata address)"


def test_a_redirecting_endpoint_is_not_followed(api: TestClient, llm: FakeLlm) -> None:
    result = api.post("/api/providers/test", json=_body(llm, "/redirect", secret_name=None)).json()
    assert result["ok"] is False and result["steps"][-1]["message"].startswith("HTTP 302")
    assert len(llm.hits) == 1


def test_a_test_that_takes_too_long_fails(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(providers_module, "CHECK_TIMEOUT_SECONDS", 0.3)
    llm.script = [(200, completion(), None, 2.0)]
    body = _body(llm, "/nomodels", secret_name=None, models=[{"model_id": "m"}])
    result = api.post("/api/providers/test", json=body).json()
    assert result == {
        "ok": False,
        "steps": [{"name": "time", "ok": False, "message": "The test took longer than 0.3 s"}],
        "warnings": [],
        "models": [],
        "lists_models": False,
    }


# ── OpenRouter ───────────────────────────────────────────────────────


@pytest.fixture
def openrouter(llm: FakeLlm, monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    """OpenRouter's fixed address points at the local server, which the test alone may reach."""
    monkeypatch.setattr(llm_client, "OPENROUTER_URL", llm.url())
    real = http_runner.address_problem
    monkeypatch.setattr(
        http_runner,
        "address_problem",
        lambda address, allow: None if address.is_loopback else real(address, allow),
    )
    return llm


def test_openrouter_has_a_fixed_address_fetches_its_models_and_checks_the_key(
    api: TestClient, openrouter: FakeLlm
) -> None:
    put_secret(api, "OPENROUTER_KEY")
    body = {
        "kind": "openrouter",
        "name": "OpenRouter",
        "secret_name": "OPENROUTER_KEY",
        "allow_http": True,
    }
    response = api.post("/api/providers", json=body)
    assert response.status_code == 201, response.text
    provider = response.json()
    assert (
        provider["base_url"] == openrouter.url()
        and provider["check_message"] == "The API key is accepted"
    )
    assert provider["allow_http"] is False  # its address is fixed and https: never for OpenRouter
    assert [h["path"] for h in openrouter.hits] == ["/v1/models", "/v1/key"]
    assert {m["model_id"] for m in provider["models"]} == {"small", "large"}
    assert all(m["enabled"] is False for m in provider["models"])
    again = api.post("/api/providers", json={**body, "name": "Second"})
    assert again.status_code == 409 and again.json()["detail"] == "OpenRouter is set up already"
    changed = api.patch(
        f"/api/providers/{provider['id']}", json={"base_url": "https://elsewhere.example/v1"}
    )
    assert (
        changed.status_code == 422 and changed.json()["detail"] == "OpenRouter has a fixed address"
    )
    assert (
        api.post(f"/api/providers/{provider['id']}/models", json={"model_id": "own"}).status_code
        == 409
    )


def test_openrouter_needs_a_secret_takes_no_address_and_no_models_by_hand(
    api: TestClient, openrouter: FakeLlm
) -> None:
    base = {"kind": "openrouter", "name": "OpenRouter"}
    assert (
        api.post("/api/providers", json=base).json()["detail"]
        == "OpenRouter needs the secret that holds its API key"
    )
    with_url = api.post(
        "/api/providers", json={**base, "secret_name": "K", "base_url": "https://x.example"}
    )
    assert with_url.json()["detail"] == "OpenRouter has a fixed address: leave base_url out"
    put_secret(api, "K")
    with_models = api.post(
        "/api/providers", json={**base, "secret_name": "K", "models": [{"model_id": "m"}]}
    )
    assert (
        with_models.status_code == 422
        and with_models.json()["detail"] == "OpenRouter's models come from its own list"
    )


def test_openrouter_with_a_refused_key_or_without_its_model_list_is_not_saved(
    api: TestClient, openrouter: FakeLlm
) -> None:
    put_secret(api, "K")
    body = {"kind": "openrouter", "name": "OpenRouter", "secret_name": "K"}
    openrouter.key_status = 401
    refused = api.post("/api/providers", json=body)
    assert refused.status_code == 422
    assert (
        refused.json()["detail"]
        == "The connection test failed: HTTP 401: the provider did not accept the API key: No auth"
    )
    openrouter.models = {"oops": 1}
    result = api.post("/api/providers/test", json=body).json()
    assert result["ok"] is False and _steps(result) == [("secret", True), ("models", False)]


# ── changing a provider ──────────────────────────────────────────────


def test_plain_changes_are_saved_without_a_test(
    api: TestClient, llm: FakeLlm, published: list[str]
) -> None:
    provider = make_provider(api, llm, is_default=False, default_model=None)
    llm.hits.clear()
    published.clear()
    changed = api.patch(
        f"/api/providers/{provider['id']}",
        json={"name": "Renamed", "default_model": "large", "is_default": True},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["name"], body["default_model"], body["is_default"]) == ("Renamed", "large", True)
    assert next(m for m in body["models"] if m["model_id"] == "large")["enabled"] is True
    assert llm.hits == [] and published == ["providers.changed"]
    assert (
        api.patch(f"/api/providers/{provider['id']}", json={"default_model": "nope"}).status_code
        == 422
    )
    cleared = api.patch(
        f"/api/providers/{provider['id']}", json={"default_model": "", "is_default": False}
    ).json()
    assert cleared["default_model"] is None and cleared["is_default"] is False


def test_only_one_provider_is_the_default(api: TestClient, llm: FakeLlm) -> None:
    first = make_provider(api, llm)
    second = api.post("/api/providers", json=_body(llm, name="Second", is_default=True)).json()
    assert second["is_default"] is True
    assert api.get(f"/api/providers/{first['id']}").json()["is_default"] is False
    api.patch(f"/api/providers/{first['id']}", json={"is_default": True})
    assert [p["is_default"] for p in api.get("/api/providers").json()] == [True, False]


def test_a_new_address_or_secret_is_tested_before_it_is_saved(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    refused = api.patch(f"/api/providers/{provider['id']}", json={"base_url": llm.url("/denied")})
    assert refused.status_code == 422 and "HTTP 401" in refused.json()["detail"]
    assert api.get(f"/api/providers/{provider['id']}").json()["base_url"] == llm.url()
    assert (
        api.patch(f"/api/providers/{provider['id']}", json={"secret_name": "MISSING"}).status_code
        == 422
    )
    assert (
        api.patch(f"/api/providers/{provider['id']}", json={"allow_http": False}).status_code == 422
    )
    assert (
        api.patch(f"/api/providers/{provider['id']}", json={"base_url": "nope"}).status_code == 422
    )
    put_secret(api, "OTHER_KEY", "another-key-value")
    llm.models = {"data": [{"id": "small"}, {"id": "brand-new"}]}
    llm.hits.clear()
    moved = api.patch(f"/api/providers/{provider['id']}", json={"secret_name": "OTHER_KEY"})
    assert moved.status_code == 200, moved.text
    assert llm.hits[0]["headers"]["authorization"] == "Bearer another-key-value"
    models = {m["model_id"]: m for m in moved.json()["models"]}
    assert models["brand-new"]["available"] is True and models["large"]["available"] is False
    # an endpoint without /models is tested with a model the provider has
    llm.hits.clear()
    no_list = api.patch(f"/api/providers/{provider['id']}", json={"base_url": llm.url("/nomodels")})
    assert no_list.status_code == 200, no_list.text
    assert llm.completions()[0]["json"]["model"] == "small"
    assert {m["model_id"] for m in no_list.json()["models"]} == set(
        models
    )  # the list is kept as it was


def test_testing_a_saved_provider_remembers_the_outcome(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    llm.models = {"broken": True}
    llm.script = [(500, {"error": {"message": "down"}})]
    result = api.post(f"/api/providers/{provider['id']}/test").json()
    assert result["ok"] is False
    assert result["steps"][-1]["message"] == 'Model "small": HTTP 500: the provider failed: down'
    saved = api.get(f"/api/providers/{provider['id']}").json()
    assert saved["check_ok"] is False and saved["check_message"] == result["steps"][-1]["message"]
    llm.models = {"data": [{"id": "small"}]}
    assert api.post(f"/api/providers/{provider['id']}/test").json()["ok"] is True
    assert api.get(f"/api/providers/{provider['id']}").json()["check_ok"] is True
    assert api.post("/api/providers/nope/test").status_code == 404


# ── models ───────────────────────────────────────────────────────────


def test_models_are_switched_on_and_off_and_relabelled(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    large = next(m for m in provider["models"] if m["model_id"] == "large")
    url = f"/api/providers/{provider['id']}/models/{large['id']}"
    on = api.patch(url, json={"enabled": True, "label": "The big one"}).json()
    assert next(m for m in on["models"] if m["id"] == large["id"]) == {
        **large,
        "enabled": True,
        "label": "The big one",
    }
    off = api.patch(url, json={"enabled": False}).json()
    assert next(m for m in off["models"] if m["id"] == large["id"])["enabled"] is False
    assert (
        api.patch(
            f"/api/providers/{provider['id']}/models/nope", json={"enabled": True}
        ).status_code
        == 404
    )
    other = api.post("/api/providers", json=_body(llm, name="Other")).json()
    assert (
        api.patch(
            f"/api/providers/{other['id']}/models/{large['id']}", json={"enabled": True}
        ).status_code
        == 404
    )


def test_refreshing_adds_new_models_and_marks_missing_ones(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    api.post(f"/api/providers/{provider['id']}/models", json={"model_id": "by-hand"})
    llm.models = {
        "data": [
            {"id": "small", "name": "Small v2"},
            {"id": "newer", "name": "Newer"},
            {"id": "by-hand"},
        ]
    }
    refreshed = api.post(f"/api/providers/{provider['id']}/models/refresh")
    assert refreshed.status_code == 200, refreshed.text
    models = {m["model_id"]: m for m in refreshed.json()["models"]}
    assert (models["small"]["label"], models["small"]["enabled"], models["small"]["available"]) == (
        "Small v2",
        True,
        True,
    )
    assert (
        models["newer"]["enabled"],
        models["newer"]["available"],
        models["newer"]["source"],
    ) == (False, True, "fetched")
    assert (
        models["large"]["available"] is False and models["large"]["source"] == "fetched"
    )  # kept, not deleted
    assert models["by-hand"]["source"] == "manual" and models["by-hand"]["available"] is True
    llm.models = {"data": MODELS_AGAIN}
    back = {
        m["model_id"]: m
        for m in api.post(f"/api/providers/{provider['id']}/models/refresh").json()["models"]
    }
    assert back["large"]["available"] is True and back["newer"]["available"] is False
    assert back["by-hand"]["available"] is True  # a model defined by hand is never marked missing


MODELS_AGAIN = [{"id": "small"}, {"id": "large"}]


def test_refreshing_fails_cleanly(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = make_provider(api, llm)
    llm.models = {"nope": 1}
    refused = api.post(f"/api/providers/{provider['id']}/models/refresh")
    assert refused.status_code == 409 and refused.json()["detail"].endswith(
        "Define the models of this provider by hand."
    )
    api.delete("/api/secrets/LLM_KEY")
    assert api.post(f"/api/providers/{provider['id']}/models/refresh").json() == {
        "detail": "Secret LLM_KEY does not exist"
    }
    put_secret(api)
    llm.models = {"data": MODELS_AGAIN}
    llm.close()
    down = api.post(f"/api/providers/{provider['id']}/models/refresh")
    assert down.status_code == 502 and down.json()["detail"].startswith(
        "The model list could not be read: The connection failed"
    )
    assert api.post("/api/providers/nope/models/refresh").status_code == 404


def test_a_refresh_that_takes_too_long_is_a_502(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = make_provider(api, llm)

    async def never(*args: Any, **kwargs: Any) -> Any:
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setattr(providers_module, "CHECK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(llm_client, "list_models", never)
    slow = api.post(f"/api/providers/{provider['id']}/models/refresh")
    assert (
        slow.status_code == 502
        and slow.json()["detail"] == "The model list could not be read: timeout"
    )


def test_models_defined_by_hand_are_managed_like_fetched_ones(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    added = api.post(
        f"/api/providers/{provider['id']}/models",
        json={"model_id": " my/model:v1 ", "label": "Mine", "enabled": False},
    )
    assert added.status_code == 201, added.text
    mine = next(m for m in added.json()["models"] if m["model_id"] == "my/model:v1")
    assert (mine["source"], mine["enabled"], mine["label"]) == ("manual", False, "Mine")
    assert (
        api.post(
            f"/api/providers/{provider['id']}/models", json={"model_id": "my/model:v1"}
        ).status_code
        == 409
    )
    assert (
        api.post(
            f"/api/providers/{provider['id']}/models", json={"model_id": "has space"}
        ).status_code
        == 422
    )
    assert (
        api.post(f"/api/providers/{provider['id']}/models", json={"model_id": "  "}).status_code
        == 422
    )
    url = f"/api/providers/{provider['id']}/models/{mine['id']}"
    assert (
        next(
            m
            for m in api.patch(url, json={"enabled": True}).json()["models"]
            if m["id"] == mine["id"]
        )["enabled"]
        is True
    )
    assert api.delete(url).status_code == 204
    small = next(m for m in provider["models"] if m["model_id"] == "small")
    refused = api.delete(f"/api/providers/{provider['id']}/models/{small['id']}")
    assert refused.status_code == 409 and "switch it off instead" in refused.json()["detail"]


def test_a_model_by_hand_that_the_provider_also_lists_keeps_one_row(
    api: TestClient, llm: FakeLlm
) -> None:
    put_secret(api)
    provider = api.post(
        "/api/providers", json=_body(llm, models=[{"model_id": "large", "label": "Chosen"}])
    ).json()
    rows = [m for m in provider["models"] if m["model_id"] == "large"]
    assert (
        len(rows) == 1
        and rows[0]["enabled"] is True
        and rows[0]["label"] == "Chosen"
        and rows[0]["source"] == "fetched"
    )


def test_a_model_in_use_cannot_be_deleted(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm)
    added = api.post(f"/api/providers/{provider['id']}/models", json={"model_id": "own"}).json()
    own = next(m for m in added["models"] if m["model_id"] == "own")
    url = f"/api/providers/{provider['id']}/models/{own['id']}"
    api.patch(f"/api/providers/{provider['id']}", json={"default_model": "own"})
    assert "it is the default model of the provider" in api.delete(url).json()["detail"]
    api.patch(f"/api/providers/{provider['id']}", json={"default_model": "small"})
    agent = make_agent(api, model="own")
    action = _post(api, "/api/actions", name="Act")
    _node(api, action, "agent", name="Ask", config={"agent_id": agent["id"], "model": "own"})
    refused = api.delete(url)
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        'The model is in use: the draft of agent "Triage"; version 1 of agent "Triage"; agent node "Ask"'
    )


def test_at_most_so_many_models_and_providers(
    api: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = make_provider(api, llm)
    monkeypatch.setattr(providers_module, "MAX_MODELS_PER_PROVIDER", 2)
    assert (
        api.post(f"/api/providers/{provider['id']}/models", json={"model_id": "third"}).status_code
        == 409
    )
    monkeypatch.setattr(providers_module, "MAX_PROVIDERS", 1)
    refused = api.post("/api/providers", json=_body(llm, name="Second"))
    assert refused.status_code == 409 and refused.json()["detail"] == "At most 1 providers"


# ── deleting ─────────────────────────────────────────────────────────


def test_a_provider_that_is_named_anywhere_cannot_be_deleted(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm, is_default=False)
    other = api.post("/api/providers", json=_body(llm, name="Other")).json()
    agent = make_agent(api, provider_id=provider["id"], model="small")
    api.put(
        f"/api/agents/{agent['id']}/draft",
        json={**agent["draft"], "provider_id": other["id"], "model": None},
    )
    refused = api.delete(f"/api/providers/{provider['id']}")
    assert refused.status_code == 409
    assert (
        refused.json()["detail"] == 'The provider is in use: version 1 of agent "Triage"'
    )  # history counts
    in_draft = api.delete(f"/api/providers/{other['id']}")
    assert in_draft.json()["detail"] == 'The provider is in use: the draft of agent "Triage"'
    api.post(f"/api/agents/{agent['id']}/draft/discard")
    action = _post(api, "/api/actions", name="Act")
    node = _node(
        api,
        action,
        "agent",
        name="Ask",
        config={"agent_id": agent["id"], "provider_id": other["id"]},
    )
    assert (
        api.delete(f"/api/providers/{other['id']}").json()["detail"]
        == 'The provider is in use: agent node "Ask"'
    )
    api.delete(f"/api/actions/{action['id']}/nodes/{node['id']}")
    assert api.delete(f"/api/providers/{other['id']}").status_code == 204
    api.delete(f"/api/actions/{action['id']}")
    api.delete(f"/api/agents/{agent['id']}")
    assert api.delete(f"/api/providers/{provider['id']}").status_code == 204
    assert api.get("/api/providers").json() == []
    assert api.delete("/api/providers/nope").status_code == 404


def test_the_default_provider_is_in_use_by_every_agent_without_a_provider(
    api: TestClient, llm: FakeLlm
) -> None:
    provider = make_provider(api, llm)
    make_agent(api)
    refused = api.delete(f"/api/providers/{provider['id']}")
    assert refused.json()["detail"] == (
        'The provider is in use: the draft of agent "Triage"; version 1 of agent "Triage"'
    )
    api.patch(f"/api/providers/{provider['id']}", json={"is_default": False})
    assert api.delete(f"/api/providers/{provider['id']}").status_code == 204


def test_many_references_are_summed_up(api: TestClient, llm: FakeLlm) -> None:
    provider = make_provider(api, llm, is_default=False)
    agent = make_agent(api, provider_id=provider["id"], model="small")
    for n in range(6):
        api.put(f"/api/agents/{agent['id']}/draft", json={**agent["draft"], "max_tokens": n + 1})
        api.post(f"/api/agents/{agent['id']}/publish")
    assert api.delete(f"/api/providers/{provider['id']}").json()["detail"].endswith("and 3 more")


# ── /api/v1 ──────────────────────────────────────────────────────────


def test_the_integration_api_has_the_same_operations(api: TestClient, llm: FakeLlm) -> None:
    put_secret(api)
    assert api.post("/api/v1/providers/test", json=_body(llm)).json()["ok"] is True
    provider = api.post("/api/v1/providers", json=_body(llm)).json()
    pid = provider["id"]
    assert api.get("/api/v1/providers").json()[0]["id"] == pid
    assert api.get(f"/api/v1/providers/{pid}").json()["name"] == "Local"
    assert (
        api.patch(f"/api/v1/providers/{pid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    )
    assert api.post(f"/api/v1/providers/{pid}/test").json()["ok"] is True
    assert api.post(f"/api/v1/providers/{pid}/models/refresh").status_code == 200
    added = api.post(f"/api/v1/providers/{pid}/models", json={"model_id": "own"})
    assert added.status_code == 201
    own = next(m for m in added.json()["models"] if m["model_id"] == "own")
    assert (
        api.patch(
            f"/api/v1/providers/{pid}/models/{own['id']}", json={"enabled": False}
        ).status_code
        == 200
    )
    assert api.delete(f"/api/v1/providers/{pid}/models/{own['id']}").status_code == 204
    assert api.delete(f"/api/v1/providers/{pid}").status_code == 204


@pytest.fixture
def published(api: TestClient) -> list[str]:
    events: list[str] = []
    bus = api.app.state.event_bus  # type: ignore[attr-defined]
    original = bus.publish

    def spy(event_type: str, data: dict[str, Any]) -> Any:
        events.append(event_type)
        return original(event_type, data)

    bus.publish = spy
    return events

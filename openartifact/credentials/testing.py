"""Connection tests of the credential types (ADR-051): an actual request to the system the credential is for.

A test returns ``(ok, message)``; the message never repeats the value (the callers of the underlying code already
mask what they know). Only the types the registry marks ``testable`` have one: for any other there is no test and the
credential is never reported as tested. The addresses go through the same checks as the nodes' own requests (no private
address unless the operator allows it, no redirects, a capped body).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from openartifact.agents import client
from openartifact.engine.http_runner import (
    AddressRefusedError,
    ConnectFailedError,
    guarded_exchange,
)
from openartifact.engine.postgres_runner import PostgresError, run_query

TIMEOUT = 15.0
LIMIT = 64 * 1024
GITHUB_API_URL = "https://api.github.com"

Tester = Callable[[str, dict[str, Any], bool], Awaitable[tuple[bool, str]]]


async def _github(value: str, settings: dict[str, Any], allow_private: bool) -> tuple[bool, str]:
    try:
        got = await guarded_exchange(
            "GET",
            f"{str(settings.get('base_url') or '').strip().rstrip('/') or GITHUB_API_URL}/user",
            {
                "Authorization": f"Bearer {value}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "OpenArtifact",
            },
            None,
            timeout=TIMEOUT,
            limit=LIMIT,
            allow_private=allow_private
            and bool(settings.get("base_url")),  # a private address only for the server of its own
        )
    except (AddressRefusedError, ConnectFailedError, ValueError) as error:
        return False, f"GitHub could not be reached: {error}"[:200]
    except Exception as error:  # a network failure of any kind is a failed test, not a crash
        return False, f"GitHub could not be reached ({type(error).__name__})"
    if got.status == 200:
        try:
            login = json.loads(got.text).get("login")
        except ValueError:
            login = None
        return True, f"GitHub accepted the token{f' (user {login})' if login else ''}"
    if got.status in (401, 403):
        return False, f"GitHub refused the token (HTTP {got.status})"
    return False, f"GitHub answered HTTP {got.status}"


async def _openrouter(
    value: str, settings: dict[str, Any], allow_private: bool
) -> tuple[bool, str]:
    try:
        await client.check_key(
            client.Endpoint(client.OPENROUTER_URL, value, False), timeout=TIMEOUT
        )
    except client.ProviderError as error:
        return False, error.message[:200]
    return True, "OpenRouter accepted the key"


async def _openai_compatible(
    value: str, settings: dict[str, Any], allow_private: bool
) -> tuple[bool, str]:
    address = str(settings.get("base_url") or "").strip().rstrip("/")
    if not address:
        return False, "Give the address of the endpoint to test the key"
    try:
        models = await client.list_models(client.Endpoint(address, value, True), timeout=TIMEOUT)
    except client.NoModelListError:
        return False, "The endpoint has no model list to test the key against"
    except client.ProviderError as error:
        return False, error.message[:200]
    return (
        True,
        f"The endpoint accepted the key and lists {len(models)} model{'' if len(models) == 1 else 's'}",
    )


async def _postgres(value: str, settings: dict[str, Any], allow_private: bool) -> tuple[bool, str]:
    try:
        await run_query(value, "SELECT 1", allow_private=allow_private, timeout=TIMEOUT, max_rows=1)
    except PostgresError as error:
        return False, str(error)[:200]
    return True, "The database accepted the connection"


TESTERS: dict[str, Tester] = {
    "github_pat": _github,
    "openrouter_api_key": _openrouter,
    "openai_compatible_api_key": _openai_compatible,
    "postgres_connection": _postgres,
}


async def test_connection(
    type_id: str, value: str, settings: dict[str, Any], *, allow_private: bool
) -> tuple[bool, str]:
    """Run the test of a type; a type without one is refused by the caller before it gets here."""
    return await TESTERS[type_id](value, settings, allow_private)

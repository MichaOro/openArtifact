"""Talking to an OpenAI-compatible endpoint (OpenRouter is one): models and one chat completion.

Every request goes through :func:`~openartifact.engine.http_runner.guarded_exchange`, the path of the
HTTP node: the address is vetted (no cloud metadata, private networks only when allowed), the
connection is pinned to the vetted address, no redirect is followed, no proxy is used and the answer is
read up to a limit. The connection test, the model list and the runtime all call the functions here, so
they cannot differ in what they allow.

Errors come out as :class:`ProviderError` with a text for people, the HTTP status if there was one and
whether trying again can help (``transient``). The API key is sent as ``Authorization: Bearer`` and is
never part of a message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from openartifact.engine.http_runner import (
    AddressRefusedError,
    ConnectFailedError,
    guarded_exchange,
)

UNENCRYPTED_REFUSED = (
    "The address uses http, so the API key and every prompt travel unencrypted: tick "
    '"Allow unencrypted connection (HTTP)" to confirm that this is fine for this endpoint'
)
OPENROUTER_URL = "https://openrouter.ai/api/v1"
#: A model list can be long (OpenRouter lists hundreds of models with their descriptions).
MODELS_LIMIT_BYTES = 16 * 1024 * 1024
COMPLETION_LIMIT_BYTES = 2 * 1024 * 1024
DETAIL_MAX_CHARS = 300
RETRY_AFTER_MAX_SECONDS = 3600.0
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class ProviderError(Exception):
    """A request to a provider that did not give a usable answer."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.transient = transient
        self.retry_after = retry_after


class NoModelListError(ProviderError):
    """The endpoint has no ``/models`` (it answered 404, 405 or 501)."""


class IncompatibleError(ProviderError):
    """The endpoint answered, but not like an OpenAI-compatible API."""


@dataclass(frozen=True)
class Endpoint:
    """Where to send a request: the base address, the key (or none) and whether private addresses
    are allowed for it (the provider's switch and the operator's, both)."""

    base_url: str
    api_key: str | None = None
    allow_private: bool = False

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


@dataclass(frozen=True)
class ToolCall:
    """A call of a tool the model asks for: ``arguments`` is the JSON text it wrote (not checked here)."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Completion:
    """One answer of a model. Usage numbers the provider did not send are ``None``, never 0."""

    text: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    status: int
    #: The tools the model wants called before it answers (only when tools were offered).
    tool_calls: tuple[ToolCall, ...] = ()

    def usage(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def _plain(text: str) -> str:
    return _CONTROL.sub(" ", text).strip()[:DETAIL_MAX_CHARS]


def _error_detail(body: Any) -> str:
    """What the provider says went wrong, as far as it follows the OpenAI error shape."""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return _plain(error["message"])
    if isinstance(error, str):
        return _plain(error)
    return ""


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """A ``Retry-After`` header as seconds from now (a number of seconds or an HTTP date)."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return min(float(value), RETRY_AFTER_MAX_SECONDS)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (when - (now or datetime.now(UTC))).total_seconds()
    return min(max(seconds, 0.0), RETRY_AFTER_MAX_SECONDS)


_STATUS_TEXT = {
    400: "the provider rejected the request",
    401: "the provider did not accept the API key",
    403: "the provider refused the request (the key has no access)",
    404: "not found (check the address and the model)",
    408: "the provider timed out",
    429: "rate limited",
}


def status_error(status: int, body: Any, headers: httpx.Headers | None = None) -> ProviderError:
    """The error for an answer that is not a success."""
    text = _STATUS_TEXT.get(status) or (
        "the provider failed" if status >= 500 else "the provider rejected the request"
    )
    detail = _error_detail(body)
    return ProviderError(
        f"HTTP {status}: {text}" + (f": {detail}" if detail else ""),
        status=status,
        transient=status in (408, 429) or status >= 500,
        retry_after=retry_after_seconds(headers.get("retry-after")) if headers else None,
    )


async def request(
    endpoint: Endpoint,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    timeout: float,
    limit: int,
) -> tuple[int, httpx.Headers, Any]:
    """One request; the answer's status, headers and JSON body (``None`` if it is not JSON).

    Raises :class:`ProviderError` when no answer came: an address that is refused or not valid is
    permanent, a failed connection or a network error may pass with another try.
    """
    headers = {"Accept": "application/json"}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        got = await guarded_exchange(
            method,
            endpoint.url(path),
            headers,
            body,
            timeout=timeout,
            limit=limit,
            allow_private=endpoint.allow_private,
        )
    except AddressRefusedError as error:
        raise ProviderError(str(error)) from error
    except ValueError as error:
        raise ProviderError("The address of the provider is not valid") from error
    except ConnectFailedError as error:
        raise ProviderError(str(error), transient=True) from error
    except httpx.TimeoutException as error:
        raise ProviderError("Timeout", transient=True) from error
    except httpx.HTTPError as error:
        raise ProviderError(
            f"The request failed ({type(error).__name__})", transient=True
        ) from error
    if got.truncated:
        raise ProviderError(
            "The answer of the provider is larger than the limit", status=got.status
        )
    try:
        parsed = json.loads(got.text)
    except ValueError:
        parsed = None
    return got.status, got.headers, parsed


async def list_models(endpoint: Endpoint, *, timeout: float = 30.0) -> list[tuple[str, str]]:
    """``(id, label)`` of the models the endpoint lists at ``/models``.

    Raises :class:`NoModelListError` when it has no such list, :class:`IncompatibleError` when the
    answer is not ``{"data": [{"id": "..."}]}``, and :class:`ProviderError` otherwise.
    """
    status, headers, body = await request(
        endpoint, "GET", "models", None, timeout=timeout, limit=MODELS_LIMIT_BYTES
    )
    if status in (404, 405, 501):
        raise NoModelListError(f"HTTP {status}: the endpoint has no /models", status=status)
    if status != 200:
        raise status_error(status, body, headers)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not all(
        isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in data
    ):
        raise IncompatibleError(
            'The answer of /models is not an OpenAI-compatible model list ({"data": [{"id": ...}]})',
            status=status,
        )
    found: dict[str, str] = {}
    for item in data:
        label = item.get("name")
        found[item["id"]] = label if isinstance(label, str) else ""
    return list(found.items())


async def check_key(endpoint: Endpoint, *, timeout: float = 30.0) -> None:
    """OpenRouter only: whether the key is accepted (its ``/models`` is public, so it cannot tell)."""
    status, headers, body = await request(
        endpoint, "GET", "key", None, timeout=timeout, limit=COMPLETION_LIMIT_BYTES
    )
    if status != 200:
        raise status_error(status, body, headers)
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise IncompatibleError(
            "The answer to the key check is not the expected one", status=status
        )


def _content(message: Any) -> str:
    """The text of an answer: a string, or the text parts of a list of content parts."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _tool_calls(message: Any) -> tuple[ToolCall, ...]:
    """The ``tool_calls`` of an answer; entries without a name are left out, arguments sent as an
    object (some providers do) become JSON text."""
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    found = []
    for number, call in enumerate(calls if isinstance(calls, list) else [], start=1):
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name:
            continue
        arguments = function.get("arguments") if isinstance(function, dict) else None
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
        ident = call.get("id")
        found.append(
            ToolCall(
                ident if isinstance(ident, str) and ident else f"call_{number}", name, arguments
            )
        )
    return tuple(found)


def _count(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


async def complete(
    endpoint: Endpoint,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float,
    limit: int = COMPLETION_LIMIT_BYTES,
    tools: list[dict[str, Any]] | None = None,
) -> Completion:
    """One chat completion (no streaming). ``tools``: OpenAI function tools the model may call; not
    sent when there are none. Raises :class:`ProviderError`."""
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    status, headers, body = await request(
        endpoint, "POST", "chat/completions", payload, timeout=timeout, limit=limit
    )
    if status != 200:
        raise status_error(status, body, headers)
    if isinstance(body, dict) and body.get("error"):
        # some providers answer 200 and report the failure in the body
        code = body["error"].get("code") if isinstance(body["error"], dict) else None
        inner = code if isinstance(code, int) and 400 <= code <= 599 else 502
        raise status_error(inner, body, headers)
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise IncompatibleError(
            "The answer is not an OpenAI-compatible chat completion (no choices)", status=status
        )
    choice = choices[0]
    finish = choice.get("finish_reason")
    usage = body.get("usage")
    return Completion(
        text=_content(choice.get("message")),
        finish_reason=finish if isinstance(finish, str) else None,
        prompt_tokens=_count(usage, "prompt_tokens"),
        completion_tokens=_count(usage, "completion_tokens"),
        total_tokens=_count(usage, "total_tokens"),
        status=status,
        tool_calls=_tool_calls(choice.get("message")) if tools else (),
    )

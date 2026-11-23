"""The HTTP Request Tool and the Code Tool: built from the frozen tool node, called by the model (ADR-040)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from openartifact.agents.local_tools import build_code_tool, build_http_tool
from openartifact.agents.tools import ToolContext
from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.executors import Limits
from tests.test_http_runner import _Handler, server

__all__ = ["server"]  # the fixture, used by name

VIEW = RunView(RunContext({"vars": {"units": "metric"}}), NodeIndex())
SECRETS = {"API_TOKEN": "tok-SECRET-123", "OTHER": "never-sent"}


def _context(*, private: bool = True, **limits: Any) -> ToolContext:
    return ToolContext(SECRETS, private, limits=Limits(**limits), view=VIEW)


def _http(port: int, **config: Any) -> dict[str, Any]:
    base = {
        "method": "GET",
        "url": f"http://127.0.0.1:{port}/weather/{{city}}?units=${{var.units}}&q={{city}}",
        "headers": "Authorization: Bearer ${secret:API_TOKEN}\nX-Lang: {lang}",
        "body": "",
        "parameters": "city: The city\nlang: A language code",
        "timeout_seconds": 5,
        "success_status": "200-299",
        "allow_private": True,
        **config,
    }
    return {
        "node_id": "t1",
        "name": "Weather",
        "kind": "http_tool",
        "tool_name": "weather",
        "config": base,
    }


# ── HTTP Request Tool ────────────────────────────────────────────────


async def test_the_http_tool_declares_its_parameters_and_fills_them_in(server: int) -> None:
    tool = build_http_tool(_http(server), _context())
    assert (tool.name, tool.parameters) == (
        "weather",
        {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "The city"},
                "lang": {"type": "string", "description": "A language code"},
            },
            "required": ["city", "lang"],
        },
    )
    answer = await tool.run({"city": "São Paulo/Centro", "lang": "de"})
    assert answer == "HTTP 200\nhello"
    method, path, headers, _ = _Handler.hits[-1]
    assert method == "GET"
    assert path == "/weather/S%C3%A3o%20Paulo%2FCentro?units=metric&q=S%C3%A3o%20Paulo%2FCentro"
    assert headers["Authorization"] == "Bearer tok-SECRET-123" and headers["X-Lang"] == "de"


async def test_a_model_value_that_looks_like_a_reference_stays_literal(server: int) -> None:
    tool = build_http_tool(
        _http(server, method="POST", url=f"http://127.0.0.1:{server}/echo", body='{"q": "{city}"}'),
        _context(),
    )
    answer = await tool.run({"city": "${secret:OTHER} ${var.units}", "lang": "{city}"})
    _, _, headers, body = _Handler.hits[-1]
    assert body == b'{"q": "${secret:OTHER} ${var.units}"}'
    assert answer == 'HTTP 200\n{"q": "${secret:OTHER} ${var.units}"}'
    assert headers["X-Lang"] == "{city}"  # one pass: a value is never filled in again
    assert "never-sent" not in answer


async def test_a_missing_parameter_and_a_refused_status_are_errors_for_the_model(
    server: int,
) -> None:
    tool = build_http_tool(
        _http(
            server,
            url=f"http://127.0.0.1:{server}/missing",
            headers="X-City: {city}\nX-Lang: {lang}",
        ),
        _context(),
    )
    assert await tool.run({"lang": "de"}) == "Error: the parameter city is missing"
    assert await tool.run({"city": "x", "lang": "de"}) == "Error: HTTP 404\nhello"
    newline = await tool.run({"city": "x", "lang": "de\r\nX-Evil: 1"})
    assert newline == "Error: The header 'X-Lang' has a control character"


async def test_the_http_tool_keeps_the_ssrf_rules(server: int) -> None:
    private = build_http_tool(_http(server), _context(private=False))
    assert (
        await private.run({"city": "x", "lang": "de"})
        == "Error: The address is not allowed (private network address)"
    )
    own_switch_off = build_http_tool(_http(server, allow_private=False), _context(private=True))
    assert (await own_switch_off.run({"city": "x", "lang": "de"})).startswith(
        "Error: The address is not allowed"
    )
    meta = build_http_tool(_http(server, url="http://169.254.169.254/{city}"), _context())
    assert (
        await meta.run({"city": "x", "lang": "de"})
        == "Error: The address is not allowed (cloud metadata address)"
    )


@pytest.mark.parametrize(
    "url", ["http://{city}/x", "https://example.com:{city}/x", "{city}://example.com/"]
)
def test_a_parameter_before_the_path_is_refused(url: str) -> None:
    with pytest.raises(
        ValueError, match=r"A parameter is allowed in the path and the query of the URL only"
    ):
        build_http_tool(_http(1, url=url), _context())


# ── Code Tool ────────────────────────────────────────────────────────


def _code(code: str, language: str = "python", **config: Any) -> dict[str, Any]:
    base = {
        "language": language,
        "code": code,
        "secrets": "API_TOKEN",
        "parameters": "a: first\nb: second",
        "timeout_seconds": 10,
        **config,
    }
    return {"node_id": "t2", "name": "Sum", "kind": "code_tool", "tool_name": "add", "config": base}


SUM = """
import json, os
data = json.load(open("context.json"))
print(data["input"]["a"] + data["input"]["b"], data["vars"]["units"], os.environ.get("API_TOKEN") == "tok-SECRET-123", "OTHER" in os.environ)
"""


async def test_the_code_tool_reads_the_arguments_as_input_and_prints_its_answer() -> None:
    tool = build_code_tool(_code(SUM), _context())
    assert tool.name == "add" and list(tool.parameters["properties"]) == ["a", "b"]
    assert await tool.run({"a": 2, "b": 3}) == "5 metric True False"


async def test_a_failing_code_tool_is_an_error_for_the_model() -> None:
    tool = build_code_tool(_code("import sys\nprint('half')\nsys.exit(3)"), _context())
    answer = await tool.run({"a": 1, "b": 1})
    assert answer.startswith("Error: Exit code 3") and "half" in answer


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        ({"code_nodes_enabled": False}, "Code nodes are disabled"),
        ({"code_blocked_in_open_mode": True}, "Code nodes need OPENARTIFACT_API_TOKEN"),
    ],
)
def test_the_code_tool_keeps_the_rules_of_the_code_node(
    limits: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_code_tool(_code(SUM), _context(**limits))


def test_a_tool_without_parameters_takes_an_empty_object() -> None:
    tool = build_code_tool(_code("print(1)", parameters=""), _context())
    assert tool.parameters == {"type": "object", "properties": {}, "required": []}
    assert json.dumps(tool.parameters)

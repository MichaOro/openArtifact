"""Mock data of a node and test cases of a Trigger (ADR-087).

A **mock** is a complete result a node hands over in a dry run instead of running (``outcome``, ``output``, ``data``, ``reason``). A **test
case** is a named set of values for the inputs of a Trigger. Both are kept in the node's config under a key with a leading underscore (like the
placement number, ADR-082: no setting, never in the settings' form) and live in the **draft only**: ``graph_of`` leaves them out of every
published version and of every snapshot of a real run. The text is data: it is never read for ``${...}``, and no secret may be in it.
"""

from __future__ import annotations

import json
from typing import Any

MOCK_KEY = "_mock"
CASES_KEY = "_cases"

#: The largest mock (its output, reason and data, as text): 64 KiB.
MAX_MOCK_BYTES = 64 * 1024
MAX_CASES = 20
MAX_CASE_NAME = 60
#: Kinds that decide or wait rather than hand over a result: a mock would have to choose a connector, so they take none.
NO_MOCK_KINDS = frozenset(
    {"trigger", "output", "complete", "stage", "action", "pipeline", "if", "switch", "timer"}
)
_MOCK_KEYS = {"enabled", "outcome", "output", "data", "reason"}


class MockError(ValueError):
    """The mock or the test cases are not acceptable (the message says why, in plain words)."""


def _no_secret(text: str, secrets: set[str]) -> None:
    if "${secret:" in text:
        raise MockError("A mock must not name a secret (${secret:...}): it is stored in plain text")
    for value in secrets:
        if value and len(value) >= 4 and value in text:
            raise MockError(
                "A mock must not hold the value of a secret: it is stored in plain text"
            )


def clean_mock(kind: str, value: Any, secrets: set[str] | None = None) -> dict[str, Any]:
    """The mock as it is stored; raises :class:`MockError`."""
    if kind in NO_MOCK_KINDS:
        raise MockError(f"A {kind} hands over no result of its own, so it takes no mock")
    if not isinstance(value, dict):
        raise MockError("A mock is an object with outcome, output, data and reason")
    for key in value:
        if key not in _MOCK_KEYS:
            raise MockError(f"A mock has no field '{key}'")
    outcome = value.get("outcome", "pass")
    if outcome not in ("pass", "fail"):
        raise MockError("The outcome of a mock is 'pass' or 'fail'")
    output, reason = value.get("output", ""), value.get("reason", "")
    if not isinstance(output, str) or not isinstance(reason, str):
        raise MockError("The output and the reason of a mock are text")
    data = value.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise MockError("The data of a mock is a JSON object")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise MockError("'enabled' is true or false")
    try:
        text = json.dumps(data)
    except (TypeError, ValueError) as error:
        raise MockError("The data of a mock is not valid JSON") from error
    if len((output + reason + text).encode()) > MAX_MOCK_BYTES:
        raise MockError(f"A mock may hold at most {MAX_MOCK_BYTES // 1024} KiB")
    _no_secret(output + "\n" + reason + "\n" + text, secrets or set())
    return {
        "enabled": enabled,
        "outcome": outcome,
        "output": output,
        "data": data,
        "reason": reason,
    }


def clean_cases(value: Any, secrets: set[str] | None = None) -> list[dict[str, Any]]:
    """The test cases as they are stored: ``[{"name": ..., "inputs": {name: text}}]``; raises :class:`MockError`."""
    if not isinstance(value, list):
        raise MockError("The test cases are a list")
    if len(value) > MAX_CASES:
        raise MockError(f"At most {MAX_CASES} test cases fit on a Trigger")
    names: set[str] = set()
    found: list[dict[str, Any]] = []
    for case in value:
        if not isinstance(case, dict) or set(case) - {"name", "inputs"}:
            raise MockError("A test case has a name and its inputs")
        name = case.get("name")
        inputs = case.get("inputs", {})
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_CASE_NAME:
            raise MockError(f"A test case needs a name of up to {MAX_CASE_NAME} characters")
        if name in names:
            raise MockError(f"There are two test cases named '{name}'")
        names.add(name)
        if not isinstance(inputs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in inputs.items()
        ):
            raise MockError("The inputs of a test case are text values by input name")
        text = json.dumps(inputs)
        if len(text.encode()) > MAX_MOCK_BYTES:
            raise MockError("A test case is too large")
        _no_secret(text, secrets or set())
        found.append({"name": name, "inputs": dict(inputs)})
    return found

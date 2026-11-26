"""The rules a setting's text must follow, by name (ADR-054).

A node kind is declared in a YAML manifest (``graph/nodes/*.yaml``); a setting there names its rule as
``check: <name>``, and the name is looked up in :data:`VALIDATORS`. A manifest therefore holds no code: what
a rule *does* lives here, reviewed with the application, and a manifest only chooses among them.

Every rule takes the text and raises :class:`SettingError` with a message that never repeats the value.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from openartifact.agents import tool_config
from openartifact.agents.render import MappingError, parse_mapping, prompt_problems
from openartifact.credentials.refs import (
    SecretReferenceError,
    check_url_references,
    names_in,
    parse_name_lines,
)
from openartifact.engine.context import VAR_NAME, ContextError, check_url_placement
from openartifact.engine.fields import FieldsError, parse_fields

MAX_DECLARED_VARIABLES = 100
GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
MAX_QUERY_VALUES = 100


class SettingError(ValueError):
    """A value does not fit the setting it is meant for (the message never repeats the value)."""


def parse_status_spec(spec: str) -> list[tuple[int, int]]:
    """``"200-299, 404"`` as ranges ``[(200, 299), (404, 404)]``; raises :class:`SettingError`."""
    ranges = []
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d{3})\s*(?:-\s*(\d{3})\s*)?", part)
        if not match:
            raise SettingError("Use status codes or ranges such as '200-299, 404'")
        low = int(match[1])
        high = int(match[2] or low)
        if not (100 <= low <= high <= 599):
            raise SettingError("Status codes are 100 to 599, a range goes upwards")
        ranges.append((low, high))
    return ranges


def _status_spec(value: str) -> None:
    parse_status_spec(value)


def _references(check: Callable[[str], None]) -> Callable[[str], None]:
    """``check`` as a setting rule: a malformed secret reference is a :class:`SettingError`."""

    def rule(value: str) -> None:
        try:
            check(value)
        except SecretReferenceError as error:
            raise SettingError(str(error)) from error

    return rule


def _url(value: str) -> None:
    check_url_references(value)
    try:
        check_url_placement(value)
    except ContextError as error:
        raise SettingError(str(error)) from error


def _text_references(value: str) -> None:
    names_in(value)


def _secret_names(value: str) -> None:
    parse_name_lines(value)


def _secret_name(value: str) -> None:
    if value.strip():
        parse_name_lines(value.strip())


def _variable_names(value: str) -> None:
    names = [line.strip() for line in value.splitlines() if line.strip()]
    if len(names) > MAX_DECLARED_VARIABLES:
        raise SettingError(f"At most {MAX_DECLARED_VARIABLES} variables")
    for name in names:
        if not VAR_NAME.fullmatch(name):
            raise SettingError(
                "One variable name per line: lowercase letters, digits and underscores, "
                "starting with a letter"
            )


def _condition_text(value: str) -> None:
    """A condition reads the run context only: a secret in it could be leaked by branching on it."""
    if "${secret" in value:
        raise SettingError(
            "${secret:NAME} cannot be used in a condition: a branch could reveal the secret"
        )
    _text_references(value)


def _agent_inputs(value: str) -> None:
    """The input mapping of an agent node: ``name = value`` per line, no secret as a source."""
    try:
        parse_mapping(value)
    except MappingError as error:
        raise SettingError(str(error)) from error
    _text_references(value)


def _agent_prompt(value: str) -> None:
    """A prompt a node sets for itself follows the agent's rule: only ``${input.NAME}``."""
    for problem in prompt_problems(value, None, "Prompt"):
        raise SettingError(problem)


def _edit_fields(value: str) -> None:
    """The fields of an Edit Fields node: ``name = value`` per line, variable names, no secret."""
    try:
        parse_fields(value)
    except FieldsError as error:
        raise SettingError(str(error)) from error


def _tool_rule(check: Callable[[str], object]) -> Callable[[str], None]:
    """A rule of ``agents/tool_config.py`` as a setting check."""

    def rule(value: str) -> None:
        try:
            check(value)
        except tool_config.ToolConfigError as error:
            raise SettingError(str(error)) from error

    return rule


def _not_secret(value: str) -> None:
    """A value of the run is put into a request, a comment or a query: never a secret."""
    if "${secret" in value:
        raise SettingError(
            "${secret:NAME} cannot be used in this setting: a secret is not a value of the run"
        )
    _text_references(value)


def _repository(value: str) -> None:
    _not_secret(value)
    text = value.strip()
    if text and "${" not in text and not GITHUB_REPOSITORY.fullmatch(text):
        raise SettingError("A repository is written owner/name")


def _github_number(value: str) -> None:
    _not_secret(value)
    text = value.strip()
    if text and "${" not in text and not re.fullmatch(r"[0-9]{1,9}", text):
        raise SettingError("A number is a whole number such as 42")


def _file_path(value: str) -> None:
    _not_secret(value)
    if ".." in value.replace("\\", "/").split("/"):
        raise SettingError("A path must not contain '..'")


def _sql_query(value: str) -> None:
    """The SQL is a fixed text: values come in as parameters, never as text of the statement."""
    if "${" in value:
        raise SettingError(
            "Put values in with $1, $2 and the Values list; a ${...} reference is never "
            "made part of the query text"
        )


def _blocked_list(value: str) -> None:
    """``table`` or ``table.column`` per line: what the author blocks for the SQLite node (it can add to the fixed floor, never lift it)."""
    from openartifact.engine.sqlite_runner import SqliteError, blocked_names

    try:
        blocked_names(value)
    except SqliteError as error:
        raise SettingError(str(error)) from None


def _board_tool_names(value: str) -> None:
    """The tool names of the OpenArtifact MCP Tool: a known name per line (the tools are the application's own, so a wrong name is
    refused, and the answer lists the names there are)."""
    from openartifact.api.board_tool_names import BOARD_TOOLS

    try:
        names = tool_config.parse_tool_names(value)
    except tool_config.ToolConfigError as error:
        raise SettingError(str(error)) from error
    for name in names:
        if name not in BOARD_TOOLS:
            raise SettingError(f"'{name}' is not a tool. The tools: {', '.join(BOARD_TOOLS)}")


def _query_values(value: str) -> None:
    _not_secret(value)
    if len(value.splitlines()) > MAX_QUERY_VALUES:
        raise SettingError(f"At most {MAX_QUERY_VALUES} values")


#: The rules a manifest may name.
VALIDATORS: dict[str, Callable[[str], None]] = {
    "status_spec": _status_spec,
    "text_references": _references(_text_references),
    "url": _references(_url),
    "secret_names": _references(_secret_names),
    "secret_name": _references(_secret_name),
    "variable_names": _variable_names,
    "condition_text": _condition_text,
    "agent_inputs": _references(_agent_inputs),
    "agent_prompt": _agent_prompt,
    "edit_fields": _edit_fields,
    "not_secret": _not_secret,
    "repository": _repository,
    "github_number": _github_number,
    "file_path": _file_path,
    "sql_query": _sql_query,
    "query_values": _query_values,
    "blocked_list": _blocked_list,
    "tool_endpoint": _tool_rule(tool_config.check_endpoint),
    "tool_names": _tool_rule(tool_config.parse_tool_names),
    "board_tool_names": _board_tool_names,
    "tool_parameters": _tool_rule(tool_config.parse_parameters),
    "tool_name": _tool_rule(tool_config.check_tool_name),
}

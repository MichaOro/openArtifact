"""Prompts and their inputs: the one place that fills ``${input.NAME}`` (pure functions, no database).

An agent declares inputs; its prompts use them as ``${input.NAME}`` and nothing else: a prompt never
reads the run context itself, so an agent does not depend on the nodes of a pipeline. The agent node
maps each input to a text that may hold the run context's references (``${node...}``, ``${var...}``,
``${card...}``), one ``name = value`` per line. Secrets are no source: ``${secret:...}`` is refused in
prompts and in mappings.

Order of a run: the mapping is resolved against the run context, the values are checked against the
declared types, then the prompts are filled in one pass (a value that contains ``${input.x}`` stays
that text). The preview uses the same functions with example values.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from openartifact.agents.artifact_inputs import ARTIFACT_SAMPLES, NO_ARTIFACT
from openartifact.agents.schemas import INPUT_NAME, InputState
from openartifact.engine.context import CANDIDATE as CONTEXT_REFERENCE
from openartifact.engine.context import ContextError, RunView

PLACEHOLDER = re.compile(r"\$\{input\.([a-z][a-z0-9_]{0,31})\}")
_INPUT_LIKE = re.compile(r"\$\{input\.[^}\r\n]{0,80}\}?")
_FOREIGN = re.compile(r"\$\{(?:(?:node|var|card)\.|\(|secret:)[^}\r\n]{0,80}\}?")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
MAPPING_MAX_LINES = 30
SECRET_IN_MAPPING = (
    "${secret:NAME} cannot be an input of an agent: the value would be sent to the provider"
)


class MappingError(ValueError):
    """The input mapping of a node is not ``name = value`` per line (the message says which line)."""


class RenderError(ValueError):
    """A prompt cannot be filled (the message names the placeholder)."""


def placeholders(text: str) -> list[str]:
    """The input names a prompt uses, in order of first use."""
    return list(dict.fromkeys(PLACEHOLDER.findall(text)))


def prompt_problems(text: str, declared: Sequence[str] | None, what: str) -> list[str]:
    """Why ``text`` cannot be a prompt of an agent that declares ``declared`` (empty: it can).

    ``declared`` ``None`` checks the form only (a node's own prompt: its agent says which inputs exist).
    """
    found: list[str] = []
    for match in _FOREIGN.finditer(text):
        shown = match[0][:60]
        found.append(
            f"{what}: {shown} is not allowed, a prompt takes only ${{input.NAME}}; "
            "declare an input and map it in the node"
        )
    for match in _INPUT_LIKE.finditer(text):
        name = PLACEHOLDER.fullmatch(match[0])
        if name is None:
            found.append(
                f"{what}: {match[0][:60]} is not a valid placeholder: input names are lowercase "
                "letters, digits and _, start with a letter and have at most 32 characters"
            )
        elif declared is not None and name[1] not in declared:
            has = (
                f"it declares: {', '.join(declared)}"
                if declared
                else "this agent declares no inputs: declare one on the agent, then map it in the node"
            )
            found.append(f"{what}: ${{input.{name[1]}}} is not a declared input ({has})")
    return list(dict.fromkeys(found))


def unused_inputs(
    mapping: Mapping[str, str],
    prompts: Sequence[str],
    declared: Sequence[str],
    artifact: Sequence[str] = (),
) -> list[str]:
    """A calm warning per input that is mapped to something (or comes from the artifact) but that no prompt uses: the
    agent does not receive it (a prompt decides what the model sees, ADR-064; nothing is added to the request on the
    side). A mapping line for an input of the artifact is stale, not "unused"."""
    text = "\n".join(prompts)
    warnings = [
        f"Input {name} is mapped but no prompt uses it: the agent does not receive it"
        for name, value in mapping.items()
        if name in declared
        and name not in artifact
        and value.strip()
        and f"${{input.{name}}}" not in text
    ]
    warnings += [
        f"Input {name} comes from the artifact but no prompt uses it: the agent does not receive it"
        for name in artifact
        if f"${{input.{name}}}" not in text
    ]
    return warnings


def parse_mapping(text: str) -> dict[str, str]:
    """``name = value`` per line as ``{name: value}`` (empty lines are skipped); :class:`MappingError`."""
    mapping: dict[str, str] = {}
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if len(lines) > MAPPING_MAX_LINES:
        raise MappingError(f"At most {MAPPING_MAX_LINES} inputs")
    for number, line in lines:
        name, equals, value = line.partition("=")
        name = name.strip()
        if name.startswith("input."):
            name = name[len("input.") :]
        if not equals or not INPUT_NAME.fullmatch(name):
            raise MappingError(f"Line {number} is not 'name = value'")
        if name in mapping:
            raise MappingError(f"Input '{name}' is mapped twice")
        if "${secret" in value:
            raise MappingError(SECRET_IN_MAPPING)
        mapping[name] = value.strip()
    return mapping


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _type_problem(kind: str, value: str) -> str | None:
    if kind == "number" and not _NUMBER.fullmatch(value.strip()):
        return "is not a number"
    if kind == "boolean" and value.strip().lower() not in ("true", "false"):
        return "is neither true nor false"
    return None


def resolve_inputs(
    specs: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, str],
    view: RunView | None,
    *,
    samples: Mapping[str, str] | None = None,
    artifact: Mapping[str, str] | None = None,
) -> list[InputState]:
    """How every declared input gets its value, and what is wrong with the mapping.

    ``view`` is the run the mapping reads. Without one (a preview) a mapping that reads the run is
    ``pending``; ``samples`` are example values that stand in for it. An input of the artifact (ADR-064) is fixed
    by the agent: its value is in ``artifact`` (by name, read by the caller) or, in a preview, an example of its
    part; a mapping line for it is ``stale`` and ignored. A mapped name that is not declared comes back as an extra
    state with an error, so nothing is ignored silently.
    """
    samples = samples or {}
    states: list[InputState] = []
    declared = {str(spec["name"]) for spec in specs}
    from_artifact = {str(s["name"]) for s in specs if s.get("source") == "artifact"}
    for spec in specs:
        name, kind = str(spec["name"]), str(spec.get("type") or "string")
        if spec.get("source") == "artifact":
            part = str(spec.get("part") or "title_body")
            state = InputState(
                name=name,
                type=part,
                required=False,
                state="unset",
                value="",
                origin="artifact",
                part=part,
            )
            if name in samples and view is None:
                state.state, state.value = "sample", samples[name]
            elif artifact is not None and name in artifact:
                state.state, state.value = "artifact", artifact[name]
            elif view is None:
                state.state, state.value = "sample", ARTIFACT_SAMPLES.get(part, "")
            else:
                state.state, state.value, state.error = "error", None, NO_ARTIFACT
            states.append(state)
            continue
        required = bool(spec.get("required"))
        state = InputState(name=name, type=kind, required=required, state="unset", value="")
        template = mapping.get(name)
        if name in samples and view is None:
            state.state, state.value, state.source = "sample", samples[name], template
        elif template is not None:
            state.source = template
            if "${secret" in template:
                state.state, state.value, state.error = "error", None, SECRET_IN_MAPPING
            elif view is None and CONTEXT_REFERENCE.search(template):
                state.state, state.value = "pending", None
            else:
                try:
                    state.value = (view or RunView()).render(template)
                    state.state = "mapped"
                except ContextError as error:
                    state.state, state.value, state.error = "error", None, str(error)
        elif spec.get("default") is not None:
            state.state, state.value = "default", _text(spec["default"])
        elif required:
            state.state, state.value = "error", None
            state.error = f"required input '{name}' is not mapped"
        if state.value is not None and state.state in ("mapped", "sample"):
            problem = _type_problem(kind, state.value)
            if problem:
                state.error = f"input '{name}' {problem}"
                state.state = "error"
            elif required and state.value == "":
                state.error = f"required input '{name}' is empty"
                state.state = "error"
        states.append(state)
    for name, template in mapping.items():
        if name in from_artifact:
            states.append(
                InputState(name=name, type="string", required=False, state="stale", source=template)
            )
        elif name not in declared:
            states.append(
                InputState(
                    name=name,
                    type="string",
                    required=False,
                    state="error",
                    source=template,
                    error=f"input '{name}' is not declared by the agent",
                )
            )
    return states


def input_problems(states: Sequence[InputState]) -> list[str]:
    return [s.error for s in states if s.state == "error" and s.error]


def fill(text: str, states: Sequence[InputState], *, preview: bool = False) -> str:
    """``text`` with every ``${input.NAME}`` replaced by its value, in one pass.

    A placeholder without a state, or with a failed one, raises :class:`RenderError`: nothing is ever
    replaced by an empty text silently. A ``preview`` keeps such a placeholder as it is written instead
    (its problem is reported with the inputs), and so does a ``pending`` input.
    """
    by_name = {s.name: s for s in states if s.state != "stale"}

    def put(match: re.Match[str]) -> str:
        state = by_name.get(match[1])
        if state is None or state.value is None or state.state == "error":
            if preview or (state is not None and state.state == "pending"):
                return match[0]
            if state is None:
                raise RenderError(f"{match[0]} is not a declared input")
            raise RenderError(state.error or f"{match[0]} has no value")
        return state.value

    return PLACEHOLDER.sub(put, text)

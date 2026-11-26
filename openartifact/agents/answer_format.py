"""The answer format of an agent: the final answer as a checked document (ADR-085).

An agent may have an *answer format*, a flat list of fields (``graph/field_schema.py``, the module and editor of the Hand Over Tool).
Then the model does not write its final answer as free text: it gives it through a tool, :data:`REPORT_TOOL`, whose parameters are
exactly these fields. The server checks the call (:func:`field_schema.validate`: types, required fields, allowed values, size). A call
that fits is the answer and ends the loop; a call that does not fit comes back to the model as the exact list of what is wrong, and the
model may call once more (**one repair**). A second call that does not fit fails the step with the reasons. A model that answers in text
without calling the tool is reminded once (:data:`REMINDER`) and then fails the step.

The checked fields become the ``data`` of the node (``${(Agent).data.passed}``) and ``output`` is their JSON text. The names of the
fields may not be names the agent's own data already has (``field_schema.RESERVED_NAMES``). Nothing in a document is read as a
reference or executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openartifact.agents.tools import Tool
from openartifact.graph import field_schema

REPORT_TOOL = "report_result"

DESCRIPTION = (
    "Report your final answer. You must give your final answer by calling this tool, not as text. "
    "Call it when you have the answer: its parameters are the fields of the answer. The answer is checked; "
    "if it does not fit you get the reasons and may correct it once."
)
REMINDER = (
    "Give your final answer by calling the tool {tool} now, with the fields it asks for. "
    "Do not write the answer as text."
)
NOT_ACCEPTED = "Error: the answer was not accepted: {problems}. Call {tool} again with a corrected answer (this is your only repair)."
ACCEPTED = "accepted"


class AnswerSink:
    """What the report tool of one node run saw: the document that passed and the reasons of every call that did not."""

    def __init__(self) -> None:
        self.document: dict[str, Any] | None = None
        self.refused: list[list[str]] = []
        self.calls = 0

    def refuse(self, text: str) -> None:
        """A call the tool never saw (its arguments were no JSON object): counts as a call that did not fit."""
        self.calls += 1
        self.refused.append([text.removeprefix("Error: ")])

    @property
    def repaired(self) -> bool:
        """A call was refused and a later one passed."""
        return self.document is not None and bool(self.refused)


@dataclass
class AnswerRun:
    """The answer format of one node run as the loop uses it: the fields, the sink of the report tool and the name the model calls it by."""

    fields: list[dict[str, Any]]
    sink: AnswerSink
    tool: str


def fields_of(value: Any) -> list[dict[str, Any]]:
    """The answer format as stored (a list of fields), checked again; ``[]`` when there is none. :class:`ValueError` says why not."""
    if not value:
        return []
    return field_schema.normalise(value, None, field_schema.RESERVED_NAMES["agent_data"])


def report_tool(fields: list[dict[str, Any]], sink: AnswerSink, limit: int | None = None) -> Tool:
    """The tool the model reports its answer with; every call goes through ``sink``."""
    size = int(limit or field_schema.DEFAULT_DOCUMENT_BYTES)

    async def run(arguments: dict[str, Any]) -> str:
        sink.calls += 1
        problems = field_schema.validate(fields, arguments, size)
        if problems:
            sink.refused.append(problems)
            return NOT_ACCEPTED.format(problems="; ".join(problems), tool=REPORT_TOOL)
        sink.document = field_schema.clean(fields, arguments)
        return ACCEPTED

    return Tool(
        REPORT_TOOL,
        DESCRIPTION,
        field_schema.json_schema(fields),
        run,
        node_name="Answer format",
    )


def rendering(document: dict[str, Any]) -> str:
    """The text ``output`` carries: the document as JSON, readable."""
    return json.dumps(document, ensure_ascii=False, indent=2)

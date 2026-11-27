"""Every tool node kind is built from the same general mechanism (ADR-079, ADR-040): the manifest (``tool: true``, the attachment port on the top, the
caption, the settings, the effect declaration) is all the generic layer reads. A tool kind may be named only where it really is a specialization: its
executor, its credential consumers, its own text. This test fails when a generic file (the editor's JavaScript, the graph and engine layers, the API)
starts to name one, which is how the OpenArtifact tool once came to be special."""

from __future__ import annotations

import re
from pathlib import Path

from openartifact.engine.context import NO_RESULT_KINDS
from openartifact.graph.node_types import NODE_TYPES

ROOT = Path(__file__).parent.parent / "openartifact"

#: Where a tool kind may be named, with the reason. Everything else is the generic layer.
ALLOWED = {
    "models/enums.py": "the enumeration of the kinds",
    "agents/handover.py": "the Hand Over Tool is the agent's way to report its answer: its executor",
    "agents/local_tools.py": "the executors of the in-process tools",
    "agents/tools.py": "the executor dispatch of the toolbox of an agent",
    "agents/board_toolbox.py": "the executor of the OpenArtifact tool",
    "credentials/types.py": "which node kinds consume a credential type",
    "api/graphs.py": "the switch that turns Execute Command on (the code kinds)",
    "engine/context_builder.py": "the Build Context node reads the Hand Over Tool's document",
}
SUFFIXES = {".py", ".js", ".html", ".css"}


def _tool_kinds() -> list[str]:
    return sorted(str(kind.value) for kind, node_type in NODE_TYPES.items() if node_type.tool)


def test_there_are_tool_kinds_and_each_has_the_same_attachment_port_in_its_manifest() -> None:
    kinds = _tool_kinds()
    assert {"code_tool", "http_tool", "openartifact_tool", "handover_tool"} <= set(kinds), kinds
    for kind in kinds:
        node_type = next(t for k, t in NODE_TYPES.items() if k.value == kind)
        assert node_type.inputs == (), f"{kind} takes no input: a tool is attached, not wired in"
        assert [(p.name, p.side) for p in node_type.outputs] == [("tool", "top")], (
            f"{kind} must have the one attachment port 'tool' on the top"
        )


def test_no_generic_file_names_a_tool_kind() -> None:
    kinds = _tool_kinds()
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in kinds) + r")\b")
    leaks: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in SUFFIXES or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            found = pattern.search(line)
            if found:
                leaks.append(f"{relative}:{number}: {found.group(1)}")
    assert not leaks, (
        "a generic file names a tool kind; the kinds differ by their manifest only (add the property to the manifest, or, if it is really "
        "a specialization of an executor, list the file in ALLOWED with the reason):\n"
        + "\n".join(leaks)
    )


def test_the_kinds_without_a_result_come_from_the_manifests() -> None:
    for kind, node_type in ((k.value, t) for k, t in NODE_TYPES.items()):
        assert (kind in NO_RESULT_KINDS) is (not node_type.produces_result), kind
    assert {
        "trigger",
        "output",
        "stage",
        "action",
        "pipeline",
        "complete",
        "code_tool",
        "openartifact_tool",
    } <= set(NO_RESULT_KINDS)
    assert "handover_tool" not in NO_RESULT_KINDS, (
        "the Hand Over Tool leaves the document it received: its manifest says so"
    )
    assert "agent" not in NO_RESULT_KINDS and "no_such_kind" not in NO_RESULT_KINDS

"""Every connection of the canvas is drawn, selected, restyled, deleted and pasted by the same code; a kind of connection (a flow edge, a tool's attachment, a
later one) differs only by a row of the table in ``static/js/editor/edge-kinds.js`` (ADR-093). This test fails when the editor's or the flow page's JavaScript
branches on a kind or writes the ports of the tool attachment outside that file: add a field to the table and read the field instead, which is how the tool
connection once came to have its own look, no line style to choose and its own bar."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "openartifact" / "static" / "js"
TABLE = "editor/edge-kinds.js"
CHECKED = ("editor", "execution")

#: What may not stand outside the table: the ports of the tool attachment as text, and the names of the kinds as text.
FORBIDDEN = re.compile(r"""["'](?:tools|attachment|flow)["']""")
#: A comparison with a port's name on an edge's side.
PORT_COMPARISON = re.compile(r"""(?:source_port|target_port)\s*[!=]==?\s*["']""")


def _files() -> list[Path]:
    return sorted(
        p
        for folder in CHECKED
        for p in (ROOT / folder).rglob("*.js")
        if p.relative_to(ROOT).as_posix() != TABLE
    )


def test_the_table_exists_and_names_every_kind_with_the_same_fields() -> None:
    text = (ROOT / TABLE).read_text(encoding="utf-8")
    for field in ("route", "arrow", "styles", "hangs", "levelsPorts", "flowDecoration", "cssName"):
        assert text.count(f"    {field}:") >= 2, f"each kind declares {field}"


def test_no_editor_file_branches_on_a_kind_of_connection_or_writes_the_tool_ports_outside_the_table() -> (
    None
):
    leaks: list[str] = []
    for path in _files():
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if FORBIDDEN.search(line) or PORT_COMPARISON.search(line):
                leaks.append(f"{relative}:{number}: {stripped[:110]}")
    assert not leaks, (
        "a file outside editor/edge-kinds.js branches on a kind of connection or names the ports of the tool attachment; read a property of "
        "kindOfEdge(edge) (add the field to the table if it is missing):\n" + "\n".join(leaks)
    )

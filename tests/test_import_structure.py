"""The import structure of the package: the dependencies of its modules run one way, and the way does not loop.

Two rules, checked over the source with :mod:`ast` (nothing is imported to check them):

- **No cycle among module-level imports.** A module-level import runs while the importing module is being loaded, so a loop of
  them can leave one module half-initialized and break the start of the application. Imports inside a function and under
  ``if TYPE_CHECKING:`` are left out: they are the documented way some modules defer a dependency (they run later, or never at
  run time), so a loop through one of them does no harm. Such loops exist; the rule keeps anyone from closing one at module level.
- **The API and the web layer are leaves.** Nothing outside ``openartifact.api``, ``openartifact.web`` and the composition root
  (``openartifact.app``) imports them, at any level (module, function, ``TYPE_CHECKING``): the API depends on the domain, never
  the reverse. A name the domain needs lives in the domain (e.g. ``agents/board_tool_names.py``, ADR-079).

An import of ``a.b.c`` also loads the packages ``a`` and ``a.b``; those are counted as dependencies too, except the packages the
importing module itself sits in (they are already loading when it runs).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

PACKAGE = "openartifact"
ROOT = Path(__file__).parent.parent / PACKAGE

#: Modules that may import the API and the web layer besides those layers themselves, with the reason.
COMPOSITION_ROOT = {
    "openartifact.app": "the composition root wires the routers and the services together",
}
#: The layers nothing else may import.
LEAF_LAYERS = ("openartifact.api", "openartifact.web")


@dataclass(frozen=True)
class Import:
    """One import of a module of the package: where it is, what it loads, and whether it runs when the importer is loaded."""

    importer: str
    target: str
    line: int
    module_level: bool


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _sources() -> dict[str, Path]:
    return {
        _module_name(path): path
        for path in sorted(ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports_in(name: str, path: Path, modules: set[str]) -> list[Import]:
    """Every import of a module of the package in one file, resolved to the modules it loads."""
    is_package = path.name == "__init__.py"
    own_package = name if is_package else name.rpartition(".")[0]
    found: list[Import] = []

    def loaded(dotted: str) -> list[str]:
        """``a.b.c`` loads ``a``, ``a.b`` and ``a.b.c``: the ones that are modules of the package."""
        parts = dotted.split(".")
        return [
            ".".join(parts[:i]) for i in range(1, len(parts) + 1) if ".".join(parts[:i]) in modules
        ]

    def add(node: ast.Import | ast.ImportFrom, module_level: bool) -> None:
        targets: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets += loaded(alias.name)
        else:
            if node.level:
                base_parts = own_package.split(".")
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                base = ".".join([*base_parts, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            targets += loaded(base)
            for alias in node.names:
                # ``from package import module`` loads the module; ``from module import name`` only the module.
                if f"{base}.{alias.name}" in modules:
                    targets.append(f"{base}.{alias.name}")
        for target in dict.fromkeys(targets):
            if target != name:
                found.append(Import(name, target, node.lineno, module_level))

    def visit(nodes: list[ast.stmt], module_level: bool) -> None:
        for node in nodes:
            if isinstance(node, ast.Import | ast.ImportFrom):
                add(node, module_level)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(node.body, False)
            elif isinstance(node, ast.If) and _is_type_checking(node.test):
                visit(node.body, False)
                visit(node.orelse, module_level)
            else:
                # A class body, a ``try``, a ``with`` or a plain ``if`` at module level runs while the module loads.
                for field in ("body", "orelse", "finalbody", "handlers", "cases"):
                    children = getattr(node, field, None) or []
                    for child in children:
                        if isinstance(child, ast.ExceptHandler | ast.match_case):
                            visit(child.body, module_level)
                    visit([c for c in children if isinstance(c, ast.stmt)], module_level)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body, True)
    return found


def _all_imports() -> list[Import]:
    sources = _sources()
    modules = set(sources)
    return [imp for name, path in sources.items() for imp in _imports_in(name, path, modules)]


def _runtime_graph(imports: list[Import]) -> dict[str, dict[str, int]]:
    """The module-level imports as ``importer -> {target: line}``, without the packages the importer sits in."""
    graph: dict[str, dict[str, int]] = {}
    for imp in imports:
        if not imp.module_level or imp.importer.startswith(imp.target + "."):
            continue
        graph.setdefault(imp.importer, {}).setdefault(imp.target, imp.line)
    return graph


def _cycles(graph: dict[str, dict[str, int]]) -> list[list[str]]:
    """One concrete loop per strongly connected component of the graph (Tarjan), as a path that starts and ends at one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[set[str]] = []

    def connect(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for nxt in graph.get(node, {}):
            if nxt not in index:
                connect(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component: set[str] = set()
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.add(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(component)

    for node in sorted(graph):
        if node not in index:
            connect(node)

    loops = []
    for component in components:
        start = min(component)
        # The shortest way from ``start`` back to itself inside the component.
        previous: dict[str, str] = {}
        queue = [start]
        while queue and start not in previous:
            current = queue.pop(0)
            for nxt in sorted(graph.get(current, {})):
                if nxt in component and nxt not in previous:
                    previous[nxt] = current
                    queue.append(nxt)
        path = [start]
        node = previous[start]
        while node != start:
            path.append(node)
            node = previous[node]
        path.append(start)
        loops.append(path[::-1])
    return loops


def _describe(loop: list[str], graph: dict[str, dict[str, int]]) -> str:
    steps = [f"{a} (line {graph[a][b]}) -> {b}" for a, b in pairwise(loop)]
    return "\n    " + "\n    ".join(steps)


def _in_layer(module: str, layers: tuple[str, ...]) -> bool:
    return any(module == layer or module.startswith(layer + ".") for layer in layers)


def test_the_source_is_found_and_the_imports_are_resolved() -> None:
    imports = _all_imports()
    assert len(_sources()) > 100, "the package's modules were not found"
    # ``from package import module`` loads the package and the module (lines left out: they move with every edit).
    edges = {(imp.importer, imp.target, imp.module_level) for imp in imports}
    validators = "openartifact.graph.validators"
    assert {
        (validators, "openartifact.agents", True),
        (validators, "openartifact.agents.tool_config", True),
        (validators, "openartifact.agents.board_tool_names", True),
    } <= edges
    assert any(not imp.module_level for imp in imports), (
        "the function-local imports were not told apart"
    )


def test_relative_deferred_and_type_checking_imports_are_classified(tmp_path: Path) -> None:
    """The package itself uses no relative import, so the forms it does not use are checked on a written module."""
    source = tmp_path / "m.py"
    source.write_text(
        "from typing import TYPE_CHECKING\n"
        "from . import sibling\n"
        "from ..other import name\n"
        "from .sibling import thing\n"
        "import openartifact.api.x as x\n"
        "if TYPE_CHECKING:\n"
        "    from openartifact.web import y\n"
        "else:\n"
        "    import openartifact.z\n"
        "class C:\n"
        "    import openartifact.k\n"
        "def f() -> None:\n"
        "    from openartifact.api import x\n",
        encoding="utf-8",
    )
    modules = {
        "openartifact",
        "openartifact.api",
        "openartifact.api.x",
        "openartifact.web",
        "openartifact.web.y",
        "openartifact.z",
        "openartifact.k",
        "openartifact.pkg",
        "openartifact.pkg.sibling",
        "openartifact.other",
    }
    found = {
        (imp.target, imp.line, imp.module_level)
        for imp in _imports_in("openartifact.pkg.m", source, modules)
    }
    assert {
        ("openartifact.pkg", 2, True),
        ("openartifact.pkg.sibling", 2, True),
        ("openartifact.other", 3, True),
        ("openartifact.pkg.sibling", 4, True),
        ("openartifact.api.x", 5, True),
        ("openartifact.web.y", 7, False),
        ("openartifact.z", 9, True),
        ("openartifact.k", 11, True),
        ("openartifact.api.x", 13, False),
    } <= found


def test_module_level_imports_have_no_cycle() -> None:
    graph = _runtime_graph(_all_imports())
    loops = _cycles(graph)
    assert not loops, (
        "the module-level imports form a cycle, which can break the start of the application; move the shared name to the module "
        "both depend on, or defer one import into the function that needs it:"
        + "".join(_describe(loop, graph) for loop in loops)
    )


def test_nothing_outside_the_api_and_web_layers_imports_them() -> None:
    offending = [
        f"{imp.importer} (line {imp.line}, {'module level' if imp.module_level else 'deferred'}) imports {imp.target}"
        for imp in _all_imports()
        if _in_layer(imp.target, LEAF_LAYERS)
        and not _in_layer(imp.importer, LEAF_LAYERS)
        and imp.importer not in COMPOSITION_ROOT
    ]
    assert not offending, (
        "the API and the web layer depend on the domain, never the reverse; move what the domain needs out of them:\n    "
        + "\n    ".join(offending)
    )

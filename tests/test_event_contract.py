"""The contract of the live event stream (``GET /api/events``): every name a page handles is listened to, every name listened to
is published, and every published name is listened to or named in ``SERVER_ONLY`` with its reason. (A listened name that no
page compares against is allowed: some pages react to any event, and a handler that looks names up in a table is not seen.)

The server sends named SSE events (``event: <type>``); the browser client (``static/js/tasks/events.js``) adds a listener only for
the names in ``EVENT_TYPES``, so a name missing there is dropped without a trace and the page's handler never runs. All three sides
are read statically: the publish calls from the AST of ``openartifact/**/*.py``, the list and the handlers from the JavaScript.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openartifact"
JS = PACKAGE / "static" / "js"
CLIENT = JS / "tasks" / "events.js"

#: Published, but no page listens to them; the browser drops them and other clients of ``GET /api/events`` receive them.
SERVER_ONLY = {
    "guards.changed": "the guard pages and popups read the guards again over REST after their own change",
    "guard.fired": "the pages see a firing as the activity.created entry published right before it (engine/runner.py)",
}

#: Wrappers whose first parameter is passed on to the bus as the event name: (file, function) -> why that is covered. Their callers
#: are scanned like any other publish call.
_ENGINE_PUBLISH = ("app.py", "publish")
FORWARDERS = {
    _ENGINE_PUBLISH: "the engine's publish (Limits.publish) records the agent facts for the guards, then calls the bus; "
    "its caller is the agent event f-string of engine/executors.py (FSTRINGS)",
}

#: f-strings used as an event name: (file, the literal prefix) -> (file, function) whose calls give the rest of the name. The agent
#: loop's ``tell("turn" | "tool_call", ...)`` (agents/loop.py) goes through agents/runtime.py (``on_event``) to the ``tell`` of
#: engine/executors.py ``_agent_events``, which publishes ``f"agent.{event}"``.
FSTRINGS = {("engine/executors.py", "agent."): ("agents/loop.py", "tell")}


def _python_files() -> Iterator[Path]:
    yield from sorted(PACKAGE.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _module(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _constants(tree: ast.Module) -> dict[str, str]:
    """The module-level string constants (``CHANGED = "credentials.changed"``)."""
    found: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    return found


def _receiver(func: ast.expr) -> str | None:
    """``self._bus`` -> ``_bus``, ``request.app.state.event_bus`` -> ``event_bus``, ``bus`` -> ``bus``."""
    if not isinstance(func, ast.Attribute):
        return None
    target = func.value
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _literal_calls(path: Path, function: str) -> set[str]:
    """The string literals passed first to the calls of ``function`` in ``path``; any other first argument fails."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function
        ):
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"{_rel(path)}:{node.lineno}: {function}(...) without a literal first argument; the event name cannot be read"
            )
            names.add(first.value)
    assert names, (
        f"{_rel(path)} has no call of {function}(...) any more: update FSTRINGS in {Path(__file__).name}"
    )
    return names


class _Publishes(ast.NodeVisitor):
    """The event names of one module's publish calls; ``problems`` lists the calls whose name cannot be read."""

    def __init__(self, path: Path, tree: ast.Module, modules: dict[str, dict[str, str]]) -> None:
        self.path = path
        self.rel = _rel(path)
        self.constants = dict(_constants(tree))
        for node in tree.body:  # constants imported from another module of the package
            if isinstance(node, ast.ImportFrom) and node.module in modules:
                for alias in node.names:
                    if alias.name in modules[node.module]:
                        self.constants[alias.asname or alias.name] = modules[node.module][
                            alias.name
                        ]
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.names: dict[str, str] = {}  # name -> where it is published (the first place)
        self.problems: list[str] = []
        self.forwarders: set[tuple[str, str]] = set()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        func = node.func
        bare = isinstance(func, ast.Name) and func.id == "publish"
        method = isinstance(func, ast.Attribute) and func.attr == "publish"
        if not (bare or method) or not node.args:
            return
        first = node.args[0]
        stringish = (
            isinstance(first, ast.Constant) and isinstance(first.value, str)
        ) or isinstance(first, ast.JoinedStr | ast.IfExp)
        on_bus = method and (_receiver(func) or "").endswith("bus")
        if (
            not on_bus
            and not stringish
            and not (isinstance(first, ast.Name) and first.id in self.constants)
        ):
            return  # another publish: a pipeline, a guard or an agent version, the history's changes
        where = f"{self.rel}:{node.lineno}"
        for name in self._resolve(first, where):
            self.names.setdefault(name, where)

    def _resolve(self, first: ast.expr, where: str) -> set[str]:
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return {first.value}
        if isinstance(first, ast.IfExp):  # "task.moved" if moved_only else "task.updated"
            return self._resolve(first.body, where) | self._resolve(first.orelse, where)
        if isinstance(first, ast.Name) and first.id in self.constants:
            return {self.constants[first.id]}
        if isinstance(first, ast.Name) and self.functions:
            function = self.functions[-1]
            if first.id in {a.arg for a in function.args.args + function.args.kwonlyargs}:
                key = (self.rel, function.name)
                if key in FORWARDERS:
                    self.forwarders.add(key)
                    return set()
                self.problems.append(
                    f"{where}: the event name is the parameter {first.id!r} of {function.name}(): "
                    "add the wrapper to FORWARDERS with the reason its callers are covered"
                )
                return set()
        if isinstance(first, ast.JoinedStr):
            head = first.values[0] if first.values else None
            simple = (
                len(first.values) == 2
                and isinstance(head, ast.Constant)
                and isinstance(first.values[1], ast.FormattedValue)
            )
            prefix = (
                head.value
                if simple and isinstance(head, ast.Constant) and isinstance(head.value, str)
                else None
            )
            source = FSTRINGS.get((self.rel, prefix)) if prefix is not None else None
            if source is None:
                self.problems.append(
                    f"{where}: an f-string event name {ast.unparse(first)}: add it to FSTRINGS with the calls that fill it"
                )
                return set()
            return {f"{prefix}{rest}" for rest in _literal_calls(PACKAGE / source[0], source[1])}
        self.problems.append(
            f"{where}: the event name {ast.unparse(first)} cannot be read statically"
        )
        return set()


def _published() -> tuple[dict[str, str], list[str], set[tuple[str, str]]]:
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in _python_files()}
    modules = {_module(path): _constants(tree) for path, tree in trees.items()}
    names: dict[str, str] = {}
    problems: list[str] = []
    forwarders: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        scan = _Publishes(path, tree, modules)
        scan.visit(tree)
        for name, where in scan.names.items():
            names.setdefault(name, where)
        problems += scan.problems
        forwarders |= scan.forwarders
    return names, problems, forwarders


def _listened() -> list[str]:
    match = re.search(r"const EVENT_TYPES = \[(.*?)\];", CLIENT.read_text(encoding="utf-8"), re.S)
    assert match, f"no EVENT_TYPES list in {CLIENT.relative_to(ROOT)}"
    return re.findall(r'"([^"]+)"', match.group(1))


#: ``type === "x.y"``, ``type !== "x.y"``, ``"x.y" === type`` and ``case "x.y":`` (the handlers name their first parameter ``type``).
_COMPARED = re.compile(
    r'\btype\s*[!=]==?\s*"([^"]+)"|"([^"]+)"\s*[!=]==?\s*type\b|\bcase\s+"([a-z_]+\.[a-z_.]+)"\s*:'
)
_PREFIX = re.compile(r'\btype\.startsWith\(\s*"([^"]+)"\s*\)')
#: ``onEvent: (type, data) =>`` and the ``handleEvent(type, data) {`` methods the pages pass the events on to.
_HANDLERS = re.compile(
    r"onEvent\s*:\s*(\(\s*[\w$]*|\S*)|^\s*handleEvent\s*\(([^,)]*)[,)][^{;]*\{", re.M
)


def _handled() -> tuple[dict[str, str], dict[str, str]]:
    """The names and the prefixes the pages compare the event type with: name -> the first file and line."""
    names: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    for path in sorted(JS.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        handlers = list(_HANDLERS.finditer(text))
        if not handlers and "connectEvents" not in text:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for handler in handlers:
            line = text.count("\n", 0, handler.start()) + 1
            if handler.group(1) is not None:
                assert re.fullmatch(r"\(\s*type", handler.group(1)), (
                    f"{rel}:{line}: onEvent must be an arrow function whose first parameter is named type "
                    f"(found {handler.group(1)!r}), or the scan of the handled names misses it"
                )
            else:
                assert handler.group(2).strip() == "type", (
                    f"{rel}:{line}: handleEvent's first parameter must be named type (found {handler.group(2)!r})"
                )
        for match in _COMPARED.finditer(text):
            name = next(group for group in match.groups() if group is not None)
            if "." in name:  # every event name has a dot (``task.created``)
                names.setdefault(name, f"{rel}:{text.count(chr(10), 0, match.start()) + 1}")
        for match in _PREFIX.finditer(text):
            prefixes.setdefault(
                match.group(1), f"{rel}:{text.count(chr(10), 0, match.start()) + 1}"
            )
    return names, prefixes


def test_every_publish_call_names_its_event_so_the_scan_sees_it() -> None:
    names, problems, forwarders = _published()
    assert not problems, "publish calls whose event name the contract cannot read:\n" + "\n".join(
        problems
    )
    assert forwarders == set(FORWARDERS), (
        f"FORWARDERS lists wrappers that are gone: {set(FORWARDERS) - forwarders}"
    )
    assert len(names) > 20, (
        f"the scan found only {sorted(names)}: is the publish call still recognised?"
    )


def test_every_name_the_server_publishes_reaches_the_browser_or_is_server_only() -> None:
    published, _, _ = _published()
    listened = set(_listened())
    missing = {
        name: where
        for name, where in published.items()
        if name not in listened and name not in SERVER_ONLY
    }
    assert not missing, (
        f"published but not in EVENT_TYPES of {CLIENT.relative_to(ROOT)} (the browser drops them); add them there, "
        f"or to SERVER_ONLY with the reason: {missing}"
    )
    stale = set(SERVER_ONLY) - set(published)
    assert not stale, f"SERVER_ONLY names that nothing publishes any more: {stale}"
    both = set(SERVER_ONLY) & listened
    assert not both, f"in EVENT_TYPES and in SERVER_ONLY at once: {both}"


def test_every_name_the_browser_listens_to_is_published() -> None:
    published, _, _ = _published()
    listened = _listened()
    assert len(listened) == len(set(listened)), (
        f"EVENT_TYPES names a type twice: {sorted(listened)}"
    )
    unknown = sorted(set(listened) - set(published))
    assert not unknown, (
        f"EVENT_TYPES of {CLIENT.relative_to(ROOT)} lists names the server never publishes: {unknown}"
    )


def test_every_name_a_page_handles_is_listened_to() -> None:
    names, prefixes = _handled()
    listened = set(_listened())
    assert len(names) > 15, (
        f"the scan found only {sorted(names)}: are the handlers still recognised?"
    )
    deaf = {name: where for name, where in names.items() if name not in listened}
    assert not deaf, (
        f"handled by a page but not in EVENT_TYPES of {CLIENT.relative_to(ROOT)}, so the handler never runs: {deaf}"
    )
    empty = {
        prefix: where
        for prefix, where in prefixes.items()
        if not any(n.startswith(prefix) for n in listened)
    }
    assert not empty, f"a prefix that matches no name of EVENT_TYPES: {empty}"

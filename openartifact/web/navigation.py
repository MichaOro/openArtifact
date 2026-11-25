"""The navigation of the web interface: entries as objects in ONE registry, drawn by one template building block
(``templates/components/nav.html``; ADR-066).

Two navigations exist, the *sidebar* (pages, with sub-entries) and the *rail* of the artifact dialog (fields, commands). Every
entry is an object of a class that inherits :class:`NavEntry`; it is registered once with its parent and its order::

    registry.register(NavLinkEntry("reports", "report", "/reports"), parent=SIDEBAR, order=50)

The text of an entry is the i18n key ``nav.<key>.label`` (and ``.tooltip``): the registry holds no texts. ``visible_when`` is a
plain function of the page's context (a dict with the request path); there is no expression language, and the context carries
neither a user nor rights (the application knows one user). The page that is *active* is derived from the registry too: the
entry whose ``href`` or ``paths`` is the longest prefix of the request path.

An application builds its registry with :func:`build_registry` (kept at ``app.state.navigation``); a test builds a fresh one.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: The root of the sidebar, and the three groups of the rail of the artifact dialog (registered as ``rail:<group>``).
SIDEBAR = "sidebar"
RAIL_GROUPS = ("fields", "custom", "actions")
Visible = Callable[[dict[str, Any]], bool]


# ── What the template draws ──────────────────────────────────────────────


@dataclass(frozen=True)
class NavItem:
    """What every drawn entry has; ``kind`` tells the template which markup to use, ``key`` names its texts."""

    key: str
    icon: str

    kind = "item"


@dataclass(frozen=True)
class NavLink(NavItem):
    """A page. With ``children`` it is a section whose children show while the user is inside it."""

    href: str = "/"
    children: tuple[NavLink, ...] = ()

    kind = "link"

    def contains(self, active: str) -> bool:
        return active == self.key or any(child.key == active for child in self.children)


@dataclass(frozen=True)
class NavGroup(NavItem):
    """A section whose sub-entries the page fills in at run time (the artifact fields of the dialog's rail)."""

    kind = "group"


@dataclass(frozen=True)
class NavField(NavItem):
    """A value of the open artifact that is changed through a list (``data-card-field``)."""

    value: str = ""
    dot: bool = True  # the coloured dot before the value

    kind = "field"


@dataclass(frozen=True)
class NavAction(NavItem):
    """A command on the open artifact (``data-card-action``)."""

    danger: bool = False

    kind = "action"


@dataclass(frozen=True)
class NavDivider:
    """A line between groups of entries."""

    key: str = ""

    kind = "divider"


# ── What is registered ───────────────────────────────────────────────────


class NavEntry(ABC):
    """Abstract base of everything that can be registered. A new kind of entry subclasses it and says how it is drawn."""

    def __init__(
        self, key: str, icon: str, *, order: int = 0, visible_when: Visible | None = None
    ) -> None:
        self.key = key
        self.icon = icon
        self.order = order
        self._visible_when = visible_when

    def is_visible(self, context: dict[str, Any]) -> bool:
        """Whether the entry is drawn for this page. A predicate that fails hides the entry and says so in the log."""
        if self._visible_when is None:
            return True
        try:
            return bool(self._visible_when(context))
        except Exception:
            logger.warning(
                "visible_when of the navigation entry %r failed: it is hidden",
                self.key,
                exc_info=True,
            )
            return False

    @abstractmethod
    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavItem | NavDivider:
        """The entry as the template draws it (``children``: its visible sub-entries)."""


class NavLinkEntry(NavEntry):
    """A page. ``paths`` are further path prefixes that belong to it (the pages of one execution belong to Executions)."""

    def __init__(
        self,
        key: str,
        icon: str,
        href: str,
        *,
        paths: tuple[str, ...] = (),
        order: int = 0,
        visible_when: Visible | None = None,
    ) -> None:
        super().__init__(key, icon, order=order, visible_when=visible_when)
        self.href = href
        self.paths = paths

    @property
    def prefixes(self) -> tuple[str, ...]:
        return (self.href, *self.paths)

    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavLink:
        return NavLink(
            self.key, self.icon, self.href, tuple(c for c in children if isinstance(c, NavLink))
        )


class NavGroupEntry(NavEntry):
    """A group whose sub-entries the page fills in (the artifact fields)."""

    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavGroup:
        return NavGroup(self.key, self.icon)


class NavFieldEntry(NavEntry):
    """A value of the open artifact, changed through a list."""

    def __init__(
        self,
        key: str,
        icon: str,
        *,
        dot: bool = True,
        order: int = 0,
        visible_when: Visible | None = None,
    ) -> None:
        super().__init__(key, icon, order=order, visible_when=visible_when)
        self.dot = dot

    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavField:
        return NavField(self.key, self.icon, dot=self.dot)


class NavActionEntry(NavEntry):
    """A command on the open artifact."""

    def __init__(
        self,
        key: str,
        icon: str,
        *,
        danger: bool = False,
        order: int = 0,
        visible_when: Visible | None = None,
    ) -> None:
        super().__init__(key, icon, order=order, visible_when=visible_when)
        self.danger = danger

    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavAction:
        return NavAction(self.key, self.icon, danger=self.danger)


class NavDividerEntry(NavEntry):
    """A line between entries."""

    def __init__(self, key: str, *, order: int = 0) -> None:
        super().__init__(key, "", order=order)

    def to_item(self, children: tuple[NavItem, ...] = ()) -> NavDivider:
        return NavDivider(self.key)


class NavigationRegistry:
    """The one place where navigation entries are registered and where the navigation of a page is built from."""

    def __init__(self) -> None:
        #: parent -> its entries by key. Parents are SIDEBAR, the key of a link (its sub-entries) or ``rail:<group>``.
        self._parents: dict[str, dict[str, NavEntry]] = {}
        #: Every key of the sidebar tree: a page is registered once there (the rail has keys of its own).
        self._sidebar_keys: set[str] = set()

    # ── registering ──────────────────────────────────────────────────

    def register(self, entry: NavEntry, *, parent: str = SIDEBAR, order: int | None = None) -> None:
        """Register ``entry`` under ``parent`` (SIDEBAR, the key of a link, or ``rail:<group>`` of :data:`RAIL_GROUPS`).

        ``order`` overrides the entry's own; the entries of a parent are drawn by order, then as they were registered.
        A key registered twice in the sidebar, or twice in one rail group, is a mistake and refused."""
        rail = parent.startswith("rail:")
        if rail and parent.removeprefix("rail:") not in RAIL_GROUPS:
            raise ValueError(f"unknown rail group {parent!r}: use rail:<{'|'.join(RAIL_GROUPS)}>")
        entries = self._parents.setdefault(parent, {})
        if entry.key in entries or (not rail and entry.key in self._sidebar_keys):
            raise ValueError(f"the navigation entry {entry.key!r} is registered already")
        if order is not None:
            entry.order = order
        entries[entry.key] = entry
        if not rail:
            self._sidebar_keys.add(entry.key)

    # ── building ─────────────────────────────────────────────────────

    def _children(self, parent: str, context: dict[str, Any]) -> list[NavItem | NavDivider]:
        """The visible entries of ``parent`` in order, each with its own visible sub-entries."""
        entries = sorted(self._parents.get(parent, {}).values(), key=lambda e: e.order)  # stable
        built: list[NavItem | NavDivider] = []
        for entry in entries:
            if not entry.is_visible(context):
                continue
            below = tuple(i for i in self._children(entry.key, context) if isinstance(i, NavItem))
            built.append(entry.to_item(below))
        return built

    def build_sidebar(self, context: dict[str, Any] | None = None) -> list[NavItem | NavDivider]:
        """The sidebar for a page."""
        return self._children(SIDEBAR, context or {})

    def build_rail(
        self, context: dict[str, Any] | None = None
    ) -> dict[str, list[NavItem | NavDivider]]:
        """The rail of the artifact dialog: the groups that have something to draw, with their entries."""
        groups = {name: self._children(f"rail:{name}", context or {}) for name in RAIL_GROUPS}
        return {name: items for name, items in groups.items() if items}

    # ── the page the user is on ──────────────────────────────────────

    def links(self) -> list[NavLinkEntry]:
        """Every page registered in the sidebar (a test checks that every page of the application is among them)."""
        return [
            entry
            for parent, entries in self._parents.items()
            if not parent.startswith("rail:")
            for entry in entries.values()
            if isinstance(entry, NavLinkEntry)
        ]

    def active_key(self, path: str) -> str:
        """The key of the sidebar entry the path belongs to: the one with the longest matching prefix (a sub-entry wins over
        its section at the same length); ``""`` when none does, so a page that is in no navigation marks nothing."""
        best, best_rank = "", (-1, -1)
        for parent, entries in self._parents.items():
            if parent.startswith("rail:"):
                continue
            depth = 0 if parent == SIDEBAR else 1
            for entry in entries.values():
                if not isinstance(entry, NavLinkEntry):
                    continue
                for prefix in entry.prefixes:
                    base = prefix.rstrip("/")
                    matches = path == prefix or (base and path.startswith(base + "/"))
                    if matches and (len(base), depth) > best_rank:
                        best, best_rank = entry.key, (len(base), depth)
        return best


# ── The entries the application ships ─────────────────────────────────────


def build_registry() -> NavigationRegistry:
    """A registry with the shipped entries; an application adds its own with :meth:`NavigationRegistry.register`."""
    registry = NavigationRegistry()
    pages: list[tuple[str, NavEntry]] = [
        (SIDEBAR, NavLinkEntry("board", "board", "/", order=10)),
        (SIDEBAR, NavLinkEntry("pipeline", "pipeline", "/pipelines", order=20)),
        (
            SIDEBAR,
            NavLinkEntry("executions", "list", "/executions", paths=("/artifacts",), order=30),
        ),
        (SIDEBAR, NavLinkEntry("settings", "settings", "/settings/providers", order=40)),
        ("pipeline", NavLinkEntry("actions", "action", "/actions", order=10)),
        ("pipeline", NavLinkEntry("guards", "shield", "/guards", order=20)),
        ("pipeline", NavLinkEntry("agents", "agent", "/agents", order=30)),
        ("settings", NavLinkEntry("providers", "plug", "/settings/providers", order=10)),
        ("settings", NavLinkEntry("credentials", "key", "/settings/credentials", order=20)),
        ("settings", NavLinkEntry("run-limits", "clock", "/settings/run-limits", order=30)),
        ("settings", NavLinkEntry("personal", "user", "/settings/personal", order=40)),
    ]
    for parent, entry in pages:
        registry.register(entry, parent=parent)
    rail: list[tuple[str, NavEntry]] = [
        ("fields", NavFieldEntry("lane", "columns", order=10)),
        ("fields", NavFieldEntry("parent", "parent", dot=False, order=20)),
        ("fields", NavDividerEntry("div-fields", order=30)),
        ("fields", NavFieldEntry("pipeline", "pipeline", order=40)),
        ("fields", NavFieldEntry("stage", "layers", order=50)),
        ("fields", NavFieldEntry("action", "action", order=60)),
        ("custom", NavDividerEntry("div-custom", order=10)),
        ("custom", NavGroupEntry("fields", "tag", order=20)),
        ("actions", NavActionEntry("archive", "inbox", order=5)),
        ("actions", NavActionEntry("delete", "trash", danger=True, order=10)),
    ]
    for group, entry in rail:
        registry.register(entry, parent=f"rail:{group}")
    return registry

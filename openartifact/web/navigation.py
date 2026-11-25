"""Navigation entries as classes, rendered by one template building block (``components/nav.html``).

The sidebar and the rail of the artifact dialog are both a :class:`Navigation`: a list of entries of
a few kinds that all share :class:`NavItem` (key, label, icon). A new entry is a new object in one
of these lists; its alignment, icon column and label are the same as everywhere else. Entries are
added with :meth:`Navigation.add`, the way an extension would add one later (ADR-014).

This module also provides a :class:`NavigationRegistry` — the single central registration point for
all navigation entries. Entries are registered with a parent and an order, and the registry builds
the sidebar and rail structures with visibility filtering via ``visible_when`` callables.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NavItem:
    """What every entry has. ``kind`` tells the template which building block to use."""

    key: str
    label: str
    icon: str
    title: str = ""  # tooltip; the label if empty

    kind = "item"

    @property
    def tooltip(self) -> str:
        return self.title or self.label


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
    """An entry with sub-entries that the page fills in at run time (the artifact fields of the dialog's rail):
    the same outlined section as a :class:`NavLink` with children, but the children are controls, not links."""

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


@dataclass
class Navigation:
    """An ordered list of entries; ``groups`` split it into blocks (e.g. fields above, actions below)."""

    name: str
    groups: dict[str, list[NavItem | NavDivider]] = field(default_factory=dict)

    def add(self, item: NavItem | NavDivider, group: str = "main") -> Navigation:
        self.groups.setdefault(group, []).append(item)
        return self


# ── Abstract base for registry entries ───────────────────────────────────


class NavEntry(ABC):
    """Abstract base for all navigation entries registered in the NavigationRegistry.

    Concrete entries (NavLinkEntry, NavGroupEntry, etc.) inherit from this and provide
    the data needed for rendering and visibility filtering.
    """

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.key = key
        self.label_key = label_key  # i18n key: nav.<key>.label
        self.icon = icon
        self.order = order
        self.visible_when = visible_when or (lambda ctx: True)

    @abstractmethod
    def to_nav_item(self) -> NavItem | NavDivider:
        """Convert this registry entry to a template-ready NavItem."""
        ...

    def is_visible(self, context: dict[str, Any]) -> bool:
        """Check if this entry should be shown in the given context."""
        try:
            return self.visible_when(context)
        except Exception:
            return False


class NavLinkEntry(NavEntry):
    """A page link with optional children."""

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        href: str = "/",
        children_keys: tuple[str, ...] = (),
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(key, label_key, icon, order=order, visible_when=visible_when)
        self.href = href
        self.children_keys = children_keys

    def to_nav_item(self) -> NavLink:
        # Children are resolved by the registry at build time
        # Strip internal prefix (e.g., "artifact:") for template compatibility
        template_key = self.key.split(":", 1)[-1] if ":" in self.key else self.key
        return NavLink(
            key=template_key,
            label=self.label_key.split(".")[-1] if "." in self.label_key else self.key,
            icon=self.icon,
            title=self.key,
            href=self.href,
            children=(),  # filled by registry
        )


class NavGroupEntry(NavEntry):
    """A group whose children are filled at runtime by the page (e.g., artifact fields)."""

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(key, label_key, icon, order=order, visible_when=visible_when)

    def to_nav_item(self) -> NavGroup:
        # Strip internal prefix (e.g., "artifact:") for template compatibility
        template_key = self.key.split(":", 1)[-1] if ":" in self.key else self.key
        return NavGroup(
            key=template_key,
            label=self.label_key.split(".")[-1] if "." in self.label_key else self.key,
            icon=self.icon,
            title=self.key,
        )


class NavFieldEntry(NavEntry):
    """An artifact field value shown in the rail."""

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        dot: bool = True,
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(key, label_key, icon, order=order, visible_when=visible_when)
        self.dot = dot

    def to_nav_item(self) -> NavField:
        # Strip internal prefix (e.g., "artifact:") for template compatibility
        template_key = self.key.split(":", 1)[-1] if ":" in self.key else self.key
        return NavField(
            key=template_key,
            label=self.label_key.split(".")[-1] if "." in self.label_key else self.key,
            icon=self.icon,
            title=self.key,
            dot=self.dot,
        )


class NavActionEntry(NavEntry):
    """An action button in the rail."""

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        danger: bool = False,
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(key, label_key, icon, order=order, visible_when=visible_when)
        self.danger = danger

    def to_nav_item(self) -> NavAction:
        # Strip internal prefix (e.g., "artifact:") for template compatibility
        template_key = self.key.split(":", 1)[-1] if ":" in self.key else self.key
        return NavAction(
            key=template_key,
            label=self.label_key.split(".")[-1] if "." in self.label_key else self.key,
            icon=self.icon,
            title=self.key,
            danger=self.danger,
        )


class NavDividerEntry(NavEntry):
    """A divider line."""

    def __init__(
        self,
        key: str,
        label_key: str,
        icon: str,
        *,
        order: int = 0,
        visible_when: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        super().__init__(key, label_key, icon, order=order, visible_when=visible_when)

    def to_nav_item(self) -> NavDivider:
        # Strip internal prefix for template compatibility
        template_key = self.key.split(":", 1)[-1] if ":" in self.key else self.key
        return NavDivider(key=template_key)


# ── Registry ──────────────────────────────────────────────────────────────


class NavigationRegistry:
    """Central registry for all navigation entries.

    Entries are registered with a parent key and an order. The registry builds
    the sidebar and rail structures, filtering by ``visible_when`` callables.

    Usage:
        registry = NavigationRegistry()
        registry.populate_builtin()  # adds the default entries
        registry.register(NavLinkEntry(...), parent="settings", order=30)
        sidebar = registry.build_sidebar(active_nav="board", context={})
    """

    def __init__(self) -> None:
        self._entries: dict[str, NavEntry] = {}
        self._children: dict[str, list[str]] = {}  # parent_key -> [child_keys] ordered

    def register(
        self,
        entry: NavEntry,
        *,
        parent: str = "sidebar",
        order: int | None = None,
    ) -> None:
        """Register a navigation entry.

        Args:
            entry: The NavEntry to register.
            parent: The parent key ("sidebar", "settings", "pipeline", "artifact", etc.)
            order: Display order among siblings. If None, uses entry.order.
        """
        if entry.key in self._entries:
            raise ValueError(f"Navigation entry with key {entry.key!r} already registered")
        self._entries[entry.key] = entry
        if order is not None:
            entry.order = order
        self._children.setdefault(parent, []).append(entry.key)
        # Keep children sorted by order
        self._children[parent].sort(key=lambda k: self._entries[k].order)

    def get(self, key: str) -> NavEntry | None:
        return self._entries.get(key)

    def build_sidebar(self, active_nav: str, context: dict[str, Any]) -> list[NavLink]:
        """Build the sidebar navigation structure for the template."""
        return self._build_navigation("sidebar", active_nav, context)

    def build_rail(self, context: dict[str, Any]) -> dict[str, list[NavItem | NavDivider]]:
        """Build the artifact rail navigation structure for the template."""
        return self._build_rail_groups("artifact", context)

    def populate_builtin(self) -> None:
        """Populate the registry with the built-in navigation entries.

        This replaces the old SIDEBAR and ARTIFACT_RAIL constants.
        """
        # Main sidebar entries
        self.register(
            NavLinkEntry(
                key="board", label_key="nav.board.label", icon="board", href="/", order=10
            ),
            parent="sidebar",
        )
        self.register(
            NavLinkEntry(
                key="pipeline",
                label_key="nav.pipeline.label",
                icon="pipeline",
                href="/pipelines",
                children_keys=("actions", "guards", "agents"),
                order=20,
            ),
            parent="sidebar",
        )
        self.register(
            NavLinkEntry(
                key="executions",
                label_key="nav.executions.label",
                icon="list",
                href="/executions",
                order=30,
            ),
            parent="sidebar",
        )
        self.register(
            NavLinkEntry(
                key="settings",
                label_key="nav.settings.label",
                icon="settings",
                href="/settings/providers",
                children_keys=("providers", "credentials", "run-limits"),
                order=40,
            ),
            parent="sidebar",
        )

        # Pipeline children
        self.register(
            NavLinkEntry(
                key="actions",
                label_key="nav.actions.label",
                icon="action",
                href="/actions",
                order=10,
            ),
            parent="pipeline",
        )
        self.register(
            NavLinkEntry(
                key="guards", label_key="nav.guards.label", icon="shield", href="/guards", order=20
            ),
            parent="pipeline",
        )
        self.register(
            NavLinkEntry(
                key="agents", label_key="nav.agents.label", icon="agent", href="/agents", order=30
            ),
            parent="pipeline",
        )

        # Settings children
        self.register(
            NavLinkEntry(
                key="providers",
                label_key="nav.providers.label",
                icon="plug",
                href="/settings/providers",
                order=10,
            ),
            parent="settings",
        )
        self.register(
            NavLinkEntry(
                key="credentials",
                label_key="nav.credentials.label",
                icon="key",
                href="/settings/credentials",
                order=20,
            ),
            parent="settings",
        )
        self.register(
            NavLinkEntry(
                key="run-limits",
                label_key="nav.run-limits.label",
                icon="clock",
                href="/settings/run-limits",
                order=30,
            ),
            parent="settings",
        )
        self.register(
            NavLinkEntry(
                key="personal",
                label_key="nav.personal.label",
                icon="user",
                href="/settings/personal",
                order=40,
            ),
            parent="settings",
        )

        # Artifact rail entries

        # Fields group - use artifact: prefix to avoid key collisions with sidebar
        self.register(
            NavFieldEntry(
                key="artifact:lane", label_key="nav.lane.label", icon="columns", order=10
            ),
            parent="artifact:fields",
        )
        self.register(
            NavFieldEntry(
                key="artifact:parent",
                label_key="nav.parent.label",
                icon="parent",
                dot=False,
                order=20,
            ),
            parent="artifact:fields",
        )
        self.register(
            NavDividerEntry(key="artifact:div-fields-1", label_key="", icon="", order=30),
            parent="artifact:fields",
        )
        self.register(
            NavFieldEntry(
                key="artifact:pipeline", label_key="nav.pipeline.label", icon="pipeline", order=40
            ),
            parent="artifact:fields",
        )
        self.register(
            NavFieldEntry(
                key="artifact:stage", label_key="nav.stage.label", icon="layers", order=50
            ),
            parent="artifact:fields",
        )
        self.register(
            NavFieldEntry(
                key="artifact:action", label_key="nav.action.label", icon="action", order=60
            ),
            parent="artifact:fields",
        )

        # Custom group (artifact fields filled by page)
        self.register(
            NavDividerEntry(key="artifact:div-custom-1", label_key="", icon="", order=10),
            parent="artifact:custom",
        )
        self.register(
            NavGroupEntry(
                key="artifact:fields", label_key="nav.fields.label", icon="tag", order=20
            ),
            parent="artifact:custom",
        )

        # Actions group
        self.register(
            NavActionEntry(
                key="artifact:delete",
                label_key="nav.delete.label",
                icon="trash",
                danger=True,
                order=10,
            ),
            parent="artifact:actions",
        )

    # ── Internal build helpers ────────────────────────────────────────────

    def _build_navigation(
        self, root: str, active_nav: str, context: dict[str, Any]
    ) -> list[NavLink]:
        """Build navigation tree from a root parent."""
        child_keys = self._children.get(root, [])
        result: list[NavLink] = []

        for key in child_keys:
            entry = self._entries.get(key)
            if not entry or not entry.is_visible(context):
                continue

            if isinstance(entry, NavLinkEntry):
                # Build children recursively
                children = self._build_children(entry.key, active_nav, context)
                # Strip internal prefix for template compatibility
                template_key = entry.key.split(":", 1)[-1] if ":" in entry.key else entry.key
                nav_link = NavLink(
                    key=template_key,
                    label=entry.label_key.split(".")[-1],
                    icon=entry.icon,
                    title=entry.key,
                    href=entry.href,
                    children=tuple(children),
                )
                result.append(nav_link)
            # Other entry types are not used in sidebar structure

        return result

    def _build_children(
        self, parent_key: str, active_nav: str, context: dict[str, Any]
    ) -> list[NavLink]:
        """Build children for a NavLinkEntry."""
        child_keys = self._children.get(parent_key, [])
        result: list[NavLink] = []

        for key in child_keys:
            entry = self._entries.get(key)
            if not entry or not entry.is_visible(context):
                continue

            if isinstance(entry, NavLinkEntry):
                children = self._build_children(entry.key, active_nav, context)
                # Strip internal prefix for template compatibility
                template_key = entry.key.split(":", 1)[-1] if ":" in entry.key else entry.key
                nav_link = NavLink(
                    key=template_key,
                    label=entry.label_key.split(".")[-1],
                    icon=entry.icon,
                    title=entry.key,
                    href=entry.href,
                    children=tuple(children),
                )
                result.append(nav_link)

        return result

    def _build_rail_groups(
        self, root: str, context: dict[str, Any]
    ) -> dict[str, list[NavItem | NavDivider]]:
        """Build rail groups from artifact:* parents."""
        groups: dict[str, list[NavItem | NavDivider]] = {}

        for group_name in ("fields", "custom", "actions"):
            parent_key = f"{root}:{group_name}"
            child_keys = self._children.get(parent_key, [])
            items: list[NavItem | NavDivider] = []

            for key in child_keys:
                entry = self._entries.get(key)
                if not entry or not entry.is_visible(context):
                    continue
                items.append(entry.to_nav_item())

            if items:
                groups[group_name] = items

        return groups


# ── Global registry instance ──────────────────────────────────────────────

registry = NavigationRegistry()
_registry_populated = False


def _ensure_populated() -> None:
    """Ensure the registry is populated exactly once."""
    global _registry_populated
    if not _registry_populated:
        registry.populate_builtin()
        _registry_populated = True


# ── Legacy constants for backward compatibility ───────────────────────────

NOTHING = "-"  # an en dash: nothing chosen yet


def _build_legacy_sidebar() -> Navigation:
    """Build the legacy SIDEBAR constant from the registry."""
    _ensure_populated()
    sidebar_items = registry.build_sidebar("board", {})
    nav = Navigation("sidebar")
    for item in sidebar_items:
        nav.add(item, "main")
    return nav


def _build_legacy_rail() -> Navigation:
    """Build the legacy ARTIFACT_RAIL constant from the registry."""
    _ensure_populated()
    rail_groups = registry.build_rail({})
    nav = Navigation("artifact")
    for group_name, items in rail_groups.items():
        for item in items:
            nav.add(item, group_name)
    return nav


# These are kept for backward compatibility with existing code
SIDEBAR = _build_legacy_sidebar()
ARTIFACT_RAIL = _build_legacy_rail()

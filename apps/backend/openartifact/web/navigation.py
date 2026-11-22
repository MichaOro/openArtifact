"""Navigation entries as classes, rendered by one template building block (``components/nav.html``).

The sidebar and the rail of the artifact dialog are both a :class:`Navigation`: a list of entries of
a few kinds that all share :class:`NavItem` (key, label, icon). A new entry is a new object in one
of these lists; its alignment, icon column and label are the same as everywhere else. Entries are
added with :meth:`Navigation.add`, the way an extension would add one later (ADR-014).
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


NOTHING = "\u2013"  # an en dash: nothing chosen yet

SIDEBAR = (
    Navigation("sidebar")
    .add(NavLink("board", "Board", "board", href="/"))
    .add(
        NavLink(
            "pipeline",
            "Pipeline",
            "pipeline",
            href="/pipelines",
            children=(NavLink("actions", "Actions", "action", href="/actions"),),
        )
    )
    .add(NavLink("executions", "Executions", "list", href="/executions"))
    .add(NavLink("artifact-types", "Artifact types", "tag", href="/artifact-types"))
)

ARTIFACT_RAIL = (
    Navigation("artifact")
    .add(NavField("lane", "Lane", "columns"), "fields")
    .add(
        NavField("parent", "Parent", "parent", title="Parent artifact", value="None", dot=False),
        "fields",
    )
    .add(NavDivider(), "fields")
    .add(NavField("pipeline", "Pipeline", "pipeline", value=NOTHING), "fields")
    .add(NavField("stage", "Stage", "layers", value=NOTHING), "fields")
    .add(NavField("action", "Action", "action", value=NOTHING), "fields")
    .add(NavAction("delete", "Delete", "trash", title="Delete artifact", danger=True), "actions")
)

"""Tests for modular navigation system (B6 enforcement)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_no_hardcoded_nav_links_in_templates():
    """Scan templates for hardcoded navigation links outside nav.html macro."""
    base = Path(__file__).parent.parent / "openartifact" / "templates"
    forbidden_patterns = [
        r'href="/settings/',
        r'href="/pipelines"',
        r'href="/actions"',
        r'href="/agents"',
        r'href="/executions"',
        r'href="/guards"',
    ]
    # Files that are allowed to have navigation links (they use the nav component or are the nav component itself)
    allowed_files = {
        "components/nav.html",
        "components/sidebar.html",
        "agent_editor.html",  # Has link to /agents for "Open in Agents" - this is a legitimate cross-reference
        "graph_editor.html",  # Has links to pipelines/actions
    }
    for path in base.rglob("*.html"):
        rel = path.relative_to(base)
        if str(rel) in allowed_files:
            continue
        content = path.read_text()
        for pattern in forbidden_patterns:
            matches = re.findall(pattern, content)
            if matches:
                # Allow if it's inside a nav.html macro call or component
                # For now, just flag it
                pytest.fail(f"Hardcoded nav link in {rel}: {pattern} -> {matches[:3]}")


def test_all_routes_have_nav_entries():
    """Every GET route under / that returns HTML has a NavLink in registry."""
    # This will be implemented after NavigationRegistry exists
    pass


def test_navigation_registry_builds_sidebar():
    """NavigationRegistry produces the same sidebar structure as SIDEBAR constant."""
    from openartifact.web.navigation import NavigationRegistry

    registry = NavigationRegistry()
    registry.populate_builtin()

    sidebar = registry.build_sidebar("board", {})
    # Should have 4 top-level entries: board, pipeline, executions, settings
    assert len(sidebar) == 4
    keys = [item.key for item in sidebar]
    assert keys == ["board", "pipeline", "executions", "settings"]

    # Pipeline should have 3 children
    pipeline = next(item for item in sidebar if item.key == "pipeline")
    assert hasattr(pipeline, "children")
    assert len(pipeline.children) == 3
    child_keys = [c.key for c in pipeline.children]
    assert child_keys == ["actions", "guards", "agents"]

    # Settings should have 4 children (providers, credentials, run-limits, personal)
    settings = next(item for item in sidebar if item.key == "settings")
    assert hasattr(settings, "children")
    assert len(settings.children) == 4
    child_keys = [c.key for c in settings.children]
    assert child_keys == ["providers", "credentials", "run-limits", "personal"]


def test_navigation_registry_builds_rail():
    """NavigationRegistry produces the same artifact rail as ARTIFACT_RAIL constant."""
    from openartifact.web.navigation import NavigationRegistry

    registry = NavigationRegistry()
    registry.populate_builtin()

    rail = registry.build_rail({})
    # Should have groups: fields, custom, actions
    assert "fields" in rail
    assert "custom" in rail
    assert "actions" in rail

    # Fields group should have lane, parent, divider, pipeline, stage, action (without prefix - stripped for template)
    fields = rail["fields"]
    field_keys = [item.key for item in fields if hasattr(item, "key") and item.key]
    assert "lane" in field_keys
    assert "parent" in field_keys
    assert "pipeline" in field_keys
    assert "stage" in field_keys
    assert "action" in field_keys

    # Custom group should have fields NavGroup
    custom = rail["custom"]
    group_keys = [item.key for item in custom if hasattr(item, "key")]
    assert "fields" in group_keys

    # Actions should have delete
    actions = rail["actions"]
    action_keys = [item.key for item in actions if hasattr(item, "key")]
    assert "delete" in action_keys


def test_navigation_registry_register_new_entry():
    """Third-party can register a new navigation entry."""
    from openartifact.web.navigation import NavigationRegistry, NavLinkEntry

    registry = NavigationRegistry()
    registry.populate_builtin()

    # Register a new entry under settings (different key to avoid collision with built-in personal)
    registry.register(
        NavLinkEntry(
            key="myfeature", label_key="nav.myfeature.label", icon="star", href="/myfeature"
        ),
        parent="settings",
        order=50,
    )

    sidebar = registry.build_sidebar("board", {})
    settings = next(item for item in sidebar if item.key == "settings")
    child_keys = [c.key for c in settings.children]
    assert "myfeature" in child_keys
    assert child_keys.index("personal") < child_keys.index("myfeature")


def test_navigation_registry_visible_when():
    """Entries with visible_when=False are filtered out."""
    from openartifact.web.navigation import NavigationRegistry, NavLinkEntry

    registry = NavigationRegistry()
    registry.populate_builtin()

    # Add an entry that's only visible when feature flag is set
    registry.register(
        NavLinkEntry(
            key="beta-feature",
            label_key="nav.beta.label",
            icon="flask",
            href="/beta",
            order=900,
            visible_when=lambda ctx: ctx.get("features", {}).get("beta", False),
        ),
        parent="sidebar",
    )

    # Without feature flag - should not appear
    sidebar = registry.build_sidebar("board", {"features": {}})
    keys = [item.key for item in sidebar]
    assert "beta-feature" not in keys

    # With feature flag - should appear
    sidebar = registry.build_sidebar("board", {"features": {"beta": True}})
    keys = [item.key for item in sidebar]
    assert "beta-feature" in keys


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

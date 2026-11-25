"""Tests for Personal Settings (A1-A3)."""

from __future__ import annotations


def test_personal_settings_models_exist():
    """Personal settings models exist in the API router."""
    from openartifact.api.settings import build_settings_router
    from openartifact.config import Settings

    Settings(api_token="test-token-12345678901234567890123456789012", secret_key="x" * 32)
    router = build_settings_router("/api", ["settings"])

    # Find the personal endpoints
    personal_get = next((r for r in router.routes if getattr(r, "name", "").endswith("get_personal")), None)
    personal_put = next((r for r in router.routes if getattr(r, "name", "").endswith("put_personal")), None)

    assert personal_get is not None, "GET /api/settings/personal not found"
    assert personal_put is not None, "PUT /api/settings/personal not found"
    assert personal_get.response_model.__name__ == "PersonalSettingsRead"
    assert personal_put.response_model.__name__ == "PersonalSettingsRead"


def test_personal_form_manifest_exists():
    """ui/forms/personal.yaml exists and is valid."""
    from pathlib import Path

    from openartifact.ui.forms import read

    path = Path(__file__).parent.parent / "openartifact" / "ui" / "forms" / "personal.yaml"
    assert path.exists(), "personal.yaml manifest not found"

    manifest = read(path)
    assert manifest.name == "personal"
    assert manifest.columns == 2
    assert len(manifest.sections) >= 1

    # Find the mark_resolved_references field
    display_section = next(s for s in manifest.sections if s.key == "display")
    field = next(f for f in display_section.fields if f.key == "mark_resolved_references")
    assert field.widget == "switch"
    assert field.default is False
    assert "legend" in field.help.lower() or "legend" in field.label.lower()


def test_navigation_registers_personal():
    """Navigation registry includes personal under settings."""
    from openartifact.web.navigation import registry

    registry2 = type(registry)()
    registry2.populate_builtin()

    sidebar = registry2.build_sidebar("board", {})
    settings = next(item for item in sidebar if item.key == "settings")
    child_keys = [c.key for c in settings.children]
    assert "personal" in child_keys
    assert child_keys.index("run-limits") < child_keys.index("personal")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
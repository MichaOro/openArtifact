# ADR-065: Modular Navigation System

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Affected chapters:** guides [UI catalog](../guides/ui-catalog.md), [Extending](../guides/extending.md), [Development](../guides/development.md); arc42 [building blocks](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Context

The application's navigation was defined in two hardcoded constants (`SIDEBAR`, `ARTIFACT_RAIL`) in `web/navigation.py`. Adding a navigation entry required editing this file directly — impossible for third-party extensions and error-prone for core development (duplicated in routes, templates). The owner mandated a **modular navigation system** with:

- An abstract base class from which all entries inherit
- Specialization per entry type (label, icon, target, children)
- A single central registration point
- One place where a change affecting all entries is made
- Visibility control via callable predicates
- Order control via integer priority

## 2. Decision

### 2.1 Abstract Base: `NavEntry`

All navigation entries inherit from `NavEntry` (abstract base class in `web/navigation.py`). It provides:

- `key: str` — unique identifier
- `label_key: str` — i18n key (`nav.<key>.label`)
- `icon: str` — icon name
- `order: int` — display order among siblings (default 0)
- `visible_when: Callable[[dict], bool]` — visibility predicate receiving context dict (default: always true)
- `is_visible(context)` — evaluates `visible_when`, catches exceptions → `False`
- `to_nav_item()` — abstract, converts to template-ready `NavItem` subclass

### 2.2 Concrete Entry Types

| Class | Purpose | Template Kind |
|-------|---------|---------------|
| `NavLinkEntry` | Page link, optional children | `link` |
| `NavGroupEntry` | Runtime-filled group (artifact fields) | `group` |
| `NavFieldEntry` | Artifact field value in rail | `field` |
| `NavActionEntry` | Action button in rail | `action` |
| `NavDividerEntry` | Separator line | `divider` |

### 2.3 Central Registry: `NavigationRegistry`

Single global instance `registry = NavigationRegistry()` with:

- `register(entry, parent, order)` — adds entry under parent, sorted by order
- `build_sidebar(active_nav, context)` → `list[NavLink]` — builds sidebar tree
- `build_rail(context)` → `dict[str, list[NavItem]]` — builds rail groups (fields, custom, actions)
- `populate_builtin()` — registers all core entries (called once at import)
- Internal keys use `artifact:` prefix to avoid collisions; stripped for template compatibility

### 2.4 Registration Pattern

```python
from openartifact.web.navigation import registry, NavLinkEntry

# Core module registers itself
registry.register(
    NavLinkEntry(key="personal", label_key="nav.personal.label", icon="user", href="/settings/personal"),
    parent="settings",
    order=30,
)

# Third-party package registers in its __init__.py
registry.register(
    NavLinkEntry(key="myfeature", label_key="nav.myfeature.label", icon="star", href="/myfeature"),
    parent="sidebar",
    order=900,
)
```

### 2.5 Visibility & Context

`visible_when` receives a `context: dict[str, Any]` containing:
- `features: dict[str, bool]` — feature flags
- No user, no permissions (single-user system per card #99)

Extensions add keys as needed; unknown keys return `False` safely.

### 2.6 Active State Derivation

Routes no longer hardcode `active_nav`. Instead, `web/routes.py` provides `_active_nav_from_path(path)` mapping paths to nav keys (exact match → prefix match → fallback "board").

### 2.7 Backward Compatibility

Legacy constants `SIDEBAR` and `ARTIFACT_RAIL` are kept, built from the registry at first use. Existing templates and code continue working unchanged.

### 2.8 Enforcement

Two tests in `tests/test_navigation_modularity.py` enforce the rules:
1. `test_no_hardcoded_nav_links_in_templates` — scans templates for hardcoded `href="/settings/..."` etc. outside allowed files
2. `test_all_routes_have_nav_entries` — (placeholder) every HTML route has a NavLink in registry

## 3. Consequences

- **Positive:** New navigation entries in ~5 lines; third-party extensible; single source of truth; visibility/order centralized; no visual change.
- **Negative:** Slight indirection; registry populated at import (must register before first request).
- **Migration:** Existing entries moved to `populate_builtin()`; settings children now dynamic via `NavGroup` in template.

## 4. Binding Rules (UI Catalog)

Added to `docs/guides/ui-catalog.md` "Binding rules for every contributor":

> **Navigation entries go through `NavigationRegistry`.** No hardcoded `<a href="/settings/...">` in templates, no manual `active_nav` strings in routes. Every page registers its entry via `registry.register(NavLinkEntry(...))`. A test enforces this.

Documented in `docs/guides/extending.md` and `.github/CONTRIBUTING.md` with cross-links.
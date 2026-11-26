# ADR-066: Modular navigation

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Implemented in:** `web/navigation.py` (`NavEntry`, `NavigationRegistry`, `build_registry`), `web/routes.py` (`_navigation_context`), `app.py` (`app.state.navigation`), `templates/components/nav.html`, `sidebar.html`, `create_task_modal.html`  
**Affected chapters:** guides [UI catalog](../../guides/ui-catalog.md), [Extending](../../guides/extending.md); [CONTRIBUTING](../../../.github/CONTRIBUTING.md)

## 1. Context

The navigation was two hard-coded constants (`SIDEBAR`, `ARTIFACT_RAIL`), and every route named its own active entry. A new
page meant editing three places and a page could be added with no entry at all. The owner asked for the same modularity as for
the node kinds and the forms: one abstract base, one central place, one place for a change that affects every entry, and a rule
that humans and AI contributors must follow.

## 2. Decision

- **One abstract base, `NavEntry`**, with a class per kind of entry (`NavLinkEntry`, `NavGroupEntry`, `NavFieldEntry`,
  `NavActionEntry`, `NavDividerEntry`). An entry has a `key`, an `icon`, an `order` and an optional `visible_when`; it says how it
  is drawn (`to_item`). A new kind of entry is a new subclass.
- **One registry, `NavigationRegistry`.** `register(entry, parent=..., order=...)` is the only way an entry gets into the
  navigation. Parents: `SIDEBAR`, the key of a link (its sub-entries) or `rail:<group>` (`fields`, `custom`, `actions`) for the
  rail of the artifact dialog. A key is registered once in the sidebar and once per rail group; a duplicate raises.
  `build_registry()` returns a registry with the shipped entries; an application holds one at `app.state.navigation`, a test
  builds its own.
- **The pages draw the registry at every request** (`_navigation_context`, a context processor of the templates): the
  sidebar, the rail and the active entry. There are no constants built at import, so an entry registered after the start is on the
  next page, and `visible_when` is evaluated for the page.
- **The active entry is derived, never named.** `NavLinkEntry` knows its `href` and further `paths` (the pages of an execution belong to
  Executions); the entry whose prefix is the longest prefix of the request path is active, a sub-entry wins over its section at the
  same length, and a page that is in no navigation marks nothing. Routes pass no `active_nav`.
- **Texts are i18n keys by entry key:** `nav.<key>.label` and `nav.<key>.tooltip` (English and German). The registry holds no texts.
- **`visible_when` is a plain function** of a context dict (`{"path": ...}`); no expression language is evaluated and the context
  has neither a user nor rights (the application knows one user; per-person rights are planned, not implemented, and the personal settings decide today what one sees and uses, for example the emergency stop). A predicate that raises hides its entry and is logged
  as a warning, never swallowed silently.
- **A page cannot be added without an entry.** `tests/test_navigation_modularity.py` checks that every page route (a GET route
  outside the API document) has an entry or is listed with a reason (the sign-in pages), and that no template has a navigation link
  of its own (the back link of the agent page is the one named exception).

## 3. Registering an entry

```python
from openartifact.web.navigation import NavLinkEntry, SIDEBAR

registry.register(NavLinkEntry("reports", "list", "/reports"), parent=SIDEBAR, order=50)
registry.register(NavLinkEntry("export", "copy", "/settings/export"), parent="settings", order=50)
```

Add `nav.reports.label` and `nav.reports.tooltip` to `i18n/locales/en.json` and `de.json`.

## 4. Consequences

- A new entry is a few lines in one place; a third party registers its own at start; the order and the visibility are decided centrally.
- The templates keep one drawing block (`components/nav.html`); the markup did not change.
- The registry is built per application, so tests see no shared state.
- Not done: entries a user may or may not see by rights (there are no users); a per-user order.

## 5. Binding rule (UI catalog, CONTRIBUTING)

Navigation entries go through `NavigationRegistry`: no `<a href>` of a page in a template, no `active_nav` in a route. The test above enforces it.

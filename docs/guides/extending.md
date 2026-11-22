# Extending the application

Two extension points exist today: kinds of nodes for pipelines and action definitions, and navigation
entries. Both are registries that the built-in parts use exactly as an extension would
([ADR-014](../architecture/adr/014-building-blocks-and-extension-points.md)). Loading third-party extensions
is not built; these are the steps for a change inside this repository. Wording: the UI says artifact,
pipeline, stage and action; the code says `task` for artifact and `graph` for how pipelines and action
definitions are stored ([ADR-015](../architecture/adr/015-vocabulary-and-storage-names.md)). Never "workflow".

All paths are below `apps/backend/openartifact/` unless stated.

## Add a kind of node

The worked example in the code is the **timer** (`TimerType`, `TimerView`, migration `0016_timer_node.py`).

1. **Name the kind.** Add a member to `NodeKind` in `models/__init__.py`.
2. **Describe it on the server.** In `graph/node_types.py` add a subclass of `NodeType`: `kind`, `label`,
   `scopes` (`PIPELINE`, `ACTION_DEFINITION` or both), `fixed` (comes with the graph) or `addable` (offered in
   the "+" menu), `chain` (a step of the main line), `inputs` / `outputs` (`Port(name, label)`), `settings`
   (`Setting(key, label, "integer" | "switch", minimum, maximum, default)`) and `links_to` if the node points
   at another graph. Override `connect_error` only where the rule differs from the common one. Add the
   instance to the registration list at the end of the file (`register(...)`). `GET /api/node-types` now
   publishes it, and the repository, the connection rules and the "+" menu follow the registry.
3. **Migrate if the schema changes.** The `kind` column has a check constraint listing the kinds, and every
   setting is a column of `graph_nodes` with a field on `NodeUpdate`/`NodeRead` in `graph/schemas.py`
   (the repository derives the allowed setting keys from the registry). Write an Alembic migration
   (`cd apps/backend && alembic revision -m "..."`), mirror the change in the models (`alembic check`
   runs in `tests/test_migrations.py` and fails on drift), and make it reversible.
4. **Execute it.** The engine runs kinds by name in `engine/runner.py` (`RunEngine._run_action` walks an action's
   definition and branches per `NodeKind`; pipelines are walked in `_walk`): add the branch. A kind without one is not executed. Keep new bounds in `node_types.py`
   (the timer's limits exist once there).
5. **Draw it in the browser.** In `static/js/editor/node-types.js` add a `NodeView` subclass with
   `static kind` equal to the server's value and call `registerView` (the built-in list at the end of the
   file). Override only what differs: `size`, `caption`, `portLocal`, `isVisible`, `canFeed` (a mirror of the
   server rule), `sections` (inspector blocks, see `static/js/editor/inspector.js`). A kind without a view
   uses the base `NodeView`.
6. **Test it.** Server: a test in `tests/test_graphs.py` (create, connect, refuse a wrong connection,
   settings bounds) and in `tests/test_engine.py` (the run goes through the new node). Browser: a flow in
   `tests/e2e/test_editor.py` if the kind has its own inspector block. If the schema changed, run
   `tests/test_migrations.py`.
7. **Document it.** One line in the glossary (arc42 chapter 12) and, if the engine behaviour is new, in
   ADR-013's successor or a new ADR.

## Add a navigation entry

Entries are objects in `web/navigation.py`; two navigations exist, `SIDEBAR` and `ARTIFACT_RAIL` (the rail of
the artifact dialog), and `components/nav.html` renders both.

1. **Add the object** to the navigation: `NavLink(key, label, icon, href=...)` (a page; `children=(...)`
   makes a section), `NavField` (a value of the open artifact chosen from a list), `NavAction` (a command),
   or a `NavDivider`. Entries are added with `.add(item, group)`.
2. **Icon.** Use an existing icon name, or add the SVG to the macro in `templates/components/icons.html` and
   its name to `icon_names` (the only place where icon paths live; `static/js/components/icons.js` clones
   them from `<template id="icons">`).
3. **Page.** A `NavLink` needs a route in `web/routes.py` that renders a template and passes
   `active_nav=<key>`. A `NavField` or `NavAction` of the rail needs its handler in the dialog script
   (`static/js/tasks/`), selected by `data-card-field` / `data-card-action`.
4. **Markup.** If the entry needs a new kind of markup, add it to `components/nav.html`; the `kind` of the
   entry picks the branch.
5. **Test it.** `tests/test_web.py` for the route and the rendered entry; `tests/e2e/` for behaviour in the
   dialog or sidebar.

## Rules for any change

- Server rule and browser mirror are written once each; keep them in step (`canFeed` mirrors `connect_error`).
- Colours only as tokens (`static/css/tokens.css`); class prefix `ge-` for the graph editor.
- No inline scripts or styles in templates: the default Content-Security-Policy is `script-src 'self'`.
- Unused code is quarantined, not left behind (`quarantine.json`, see [CONTRIBUTING](../../.github/CONTRIBUTING.md)).
- Run `ruff`, `mypy` and `pytest` ([testing guide](testing.md)) before the change is done.

# ADR-065: Every window is a form manifest

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-062](062-configuration-windows-as-data.md) (from "may be" to "is"), [ADR-059](059-one-catalog-of-ui-building-blocks.md) (a binding rule)  
**Implemented in:** `ui/forms/credential.yaml`, `static/js/components/credential-dialog.js` (the first window moved after the pilot), `tests/test_window_rule.py`  
**Affected chapters:** guide [ui-catalog](../../guides/ui-catalog.md) (*Binding rules for every contributor*), guide [extending](../../guides/extending.md) (*A configuration window is a manifest*), [CONTRIBUTING](../../../.github/CONTRIBUTING.md)

## 1. Context

ADR-062 made the form of a window data (a YAML manifest drawn by one component) and ADR-063 made every manifest window
rearrangeable by the person who runs the application. Both only said that a window *can* be described this way, and one window,
the guard editor, was moved as a pilot. The windows built by hand next to it (the credential window, the provider dialog, the
retention rule, lane settings, ...) each have their own markup, their own spacing and help lines, and none of them has the layout
handle. The owner's decision (2026-11-25): **from now on every window and every overlay is made as a form manifest**, so that
spacing, help tooltips, columns, errors and the arrangement are the same everywhere and the owner can adapt every window himself.

## 2. Decision

- **A window that configures or asks for something is a form manifest.** Every new window, overlay or dialog that shows
  fields the user fills in or changes is described in `ui/forms/<name>.yaml` (ADR-062), drawn by `FormView`
  (`static/js/components/form-view.js`) and carries the layout handle (`WindowLayout`, ADR-063, window name `forms/<name>`).
  This binds everyone who adds or changes an interface: people, scripts and AI agents alike.
- **What the code decides stays in code, not in the markup:** which choices exist (`overrides`), what a custom widget needs
  (`context`), what a change implies (`normalize`), the frame around the form (title, Save, Cancel) and the request. What
  needs a control the built-in widgets lack is a registered widget (`registerWidget`), never a hand-built block of a window.
- **Named exceptions, with a reason, are the only handmade windows:**
  - a *question* ("Delete it?", "Leave without saving?"): the shared confirm and leave components, no fields;
  - a window that only *displays* (a published version, a token shown once);
  - a *picker* or a *name dialog* that is one choice or one name (until it is migrated, binding rule 3);
  - a window with its own two-pane canvas (the node settings dialog has its own data, ADR-053/054; the create-artifact dialog
    and the artifact-fields dialog are dynamic) until a manifest widget covers it.
  An exception is written down in `tests/test_window_rule.py` with its reason; a window that is in neither list fails the test.
- **Existing windows are moved when they are touched**, not all at once and not unasked: the owner schedules a migration, or
  a change that rebuilds a window moves it. The list of windows that are still handmade is in
  [extending](../../guides/extending.md#a-configuration-window-is-a-manifest) and in the test.
- **The credential window is the first moved:** `credential.yaml` has the kind, the name, the description and one field per
  field of every credential type (`github_pat.value`, `github_pat.base_url`, ...). `tests/test_forms.py` checks that the manifest
  and `credentials/types.py` name the same fields with the same labels, secrets and limits.

## 3. Consequences

- A new window costs a YAML file, German overrides (`forms.<name>.*`) and a few lines that draw it; it gets columns, tooltips,
  errors, the layout handle and export for free.
- `tests/test_window_rule.py` makes the rule a check: every `modal(...)` of the templates is a manifest window or a named
  exception, so the rule cannot be forgotten by the next person or the next tool.
- Fields that depend on a *kind* (a credential type) are declared per kind with `visible_when`; a few more keys in the manifest, but
  every field can be arranged by the owner, which a generated block cannot.
- A secret value is a `text` field with `config: {secret: true}` (type password, never prefilled); `config: {readonly: true}`
  shows a value that cannot change (the name of an existing credential).

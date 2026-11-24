# ADR-062: Configuration windows as data (form manifests)

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-059](059-one-catalog-of-ui-building-blocks.md) (a section of a window is a component too), [ADR-060](060-guards.md) (the guard editor)  
**Implemented in:** `ui/forms.py`, `ui/forms/guard.yaml`, `api/forms.py` (`/api/forms`), `static/js/components/form-view.js`, `form-plan.js`, `form-widgets.js`, `static/js/guards/widgets.js`, `guards/editor-window.js`  
**Affected chapters:** guide [extending](../../guides/extending.md) (*A configuration window is a manifest*), [UI catalog](../../guides/ui-catalog.md), [guards](../../guides/guards.md); arc42 [05.04](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Context

The node kinds are declared in YAML (ADR-054) and one renderer draws their settings (ADR-053). The windows that
configure *other* things (a guard, a provider, a credential, a retention rule, an agent version) were hand-built: every
window built its own sections, its own label-and-help markup and its own column of controls. The guard editor had grown
into one endless column (1024 × 1216 px for a typical guard), contradicting *as wide as necessary, as narrow as possible*
([ADR-059](059-one-catalog-of-ui-building-blocks.md) §4). The owner's decision: describe such windows as data, like the
node kinds, so that spacing, columns, sections, help tooltips and the names of things are the same everywhere, and so
that a third party can describe a window without writing layout code.

## 2. Decision

- **A form is a YAML manifest** in `ui/forms/<name>.yaml`, validated by pydantic models like the node manifests
  (`schema: 1`, unknown keys refused, a bad file stops the start naming the file). It declares **sections** (key, title,
  `column`: `1`, `2`, `auto` or `full`, an optional `weight`) with **fields** (key as a dotted path into the values, a
  **widget**, label, help, placeholder, options, default, `required`, `min`/`max`/`step`, `advanced`, `visible_when`,
  free `config`). `columns: 2` and `width: <rem>` say how many columns a wide window has and how wide the form is. No code
  in a manifest.
- **A widget is chosen by name** from a registry in the browser (`form-widgets.js`): the built-in `text`, `number`,
  `textarea`, `select`, `choice` (one of a few as chips), `chips` (several, ticked), `switch`, `readonly`; the
  application registers more for what needs code (the guard form: `rule-tree`, `escalation-steps`, `action-picker`, in
  `guards/widgets.js`). A third party registers one with `registerWidget(name, factory)` and `register_widget(name)` on the
  server so a manifest may name it; a test checks that every widget a shipped manifest names exists in the browser.
- **One renderer.** `FormView` (`form-view.js`) draws a manifest: sections as fieldsets in blocks (a `full` section is a
  row of its own, the others share two columns on a window wider than 52 rem and stack below it; `auto` fills the
  column with less weight), each field with its label, the help in an (i) tooltip (`info-tip.js`, ADR-053), the widget and a
  line for its error. Fields marked `advanced` are folded behind *More options*. It edits the `values` object it is given,
  draws again when a change decides what is there (a `visible_when`, or a field naming it in `config.depends_on`) keeping
  the focus, and offers `validate()` for the limits (`required`, `min`, `max`). The layout rules are pure functions
  (`form-plan.js`, unit-tested). The window around the form (title with the inline-renamed name, "Used in N places", tabs,
  Save and Cancel) stays a component of its own (ADR-059 §5).
- **Texts** are English in the manifest and overridden by key in the locale files, like the node kinds (ADR-056):
  `forms.<form>.sections.<section>.title`, `forms.<form>.fields.<key>.label` / `.help` / `.placeholder` and
  `.options.<value>`; what a language does not override stays English. `GET /api/forms` and `/api/forms/{name}` serve the
  description in the language of the request. `tools/check_i18n.py` leaves `forms.*` keys alone (they are overrides), and
  `tests/test_forms.py` checks that every override names a form, section, field or option that exists and that German has
  a text for every text of the shipped forms.
- **What the code decides** is handed to the form by the window, not written in the manifest: `overrides` per field key
  (the consequences of a guard that exist and which are not built yet), a `context` for custom widgets (the rule schema,
  the actions to choose from) and a `normalize(values, key)` hook (a trigger gets the defaults of its kind).
- **Pilot: the guard editor.** Its Settings and Logic are `ui/forms/guard.yaml`. It is 850 × 746 px for a typical guard
  (was 1024 × 1216): trigger and consequence side by side, the condition across the whole width (a rule builder needs
  about 40 rem), escalation and the guard's action side by side, *Held for* and *Quiet after firing* folded as advanced.
  "Can watch" is no longer shown (see §3).
- **Not for questions.** A "Do you want to delete this?" is the shared confirm component; a form manifest is for windows
  that configure something.

## 3. Consequences

- Moving a window to a manifest means describing it in YAML, adding German overrides and, for what is not a built-in
  widget, registering a widget once; layout, help, errors and advanced fields come with it. The other windows are
  candidates, not migrated (the owner schedules them): the list is in the guide.
- Container queries do not work in a window that is as wide as its content (`container-type` removes the intrinsic
  width), so the two columns are decided by the width of the viewport (52 rem) and the form's own `width`.
- **"Can watch"** (`scope_types`: the kinds of scope a guard may be attached to) is hidden in the editor, not removed:
  the data, the API, the validation and the template metadata stay, existing definitions keep their value and a new one
  has all three. The control is kept as `guards/scope-chips.js`, unused, with an entry in `quarantine.json` (14 days), so
  that the owner can decide in one or two weeks whether it comes back.
- A form that names a widget nobody registered draws a note in place of the field (and the test fails for a shipped one).

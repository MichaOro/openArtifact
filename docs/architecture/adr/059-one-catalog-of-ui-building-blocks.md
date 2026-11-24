# ADR-059: One catalog of UI building blocks

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-036](036-ui-conventions-and-lane-settings.md) (the destructive look is one variant of the catalog; its rules stay)  
**Amended by:** —  
**Implemented in:** `static/css/tokens.css` (the `--btn-*` and `--button-primary-*` tokens, `--color-pulse`), `static/css/forms.css` (`.button` and its variants, `.chip-button`, the one disabled look), `static/css/components.css` (`.icon-button`, `.task-tab`), `static/css/avatar.css`; tests `tests/e2e/test_ui_catalog.py`  
**Affected chapters:** [UI catalog guide](../../guides/ui-catalog.md), [Extending](../../guides/extending.md), arc42 [05.04](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Context

The same complaint kept coming back, one control at a time: a button that is dark on dark in the dark theme, a
"Start processing" that is purple on a dark card, a "Close" that looked different from the others, a disabled button that
could not be read. Each was fixed where it was seen. The cause was that a control's look was decided per feature: ad-hoc
classes (`.card-run`, `.history__filter-button`, `.ge-stage__add`), an `opacity` for every disabled state (and two of them
stacked on one button), and colours picked where they were used. Every new dialog repeated the risk, and a third party
that extends the application (a node kind, a page, later a community hub) would have had to guess which classes to use and
would have re-invented its own buttons, each with its own dark mode.

## 2. Decision

**Every control of the interface comes from one catalog with one definition.** A feature does not style a control; it
picks a catalog component and, where nothing fits, adds a variant to the catalog.

- **A small set of components.** Buttons (`.button` with `--primary`, `--ghost` for the outlined secondary, `--danger`,
  `--sm`; `.is-danger` for anything that deletes or discards), `.icon-button`, `.chip-button` (a pill: a toggle with
  `aria-pressed`, or a small action), tabs (`.task-tab`), navigation entries (`.nav-link`), menu items and popover options,
  and the other building blocks that already live in `static/js/components/` and the shared stylesheets (dialogs, popovers,
  the avatar, the info tip, the switch). The [guide](../../guides/ui-catalog.md) lists them with what to use when.
- **One token set, two themes.** Colour and state come from tokens (`tokens.css`); the button tokens (`--btn-*`,
  `--button-primary-*`) are defined once, with the same formulas in both themes and only a few scalars that differ. No
  component contains a colour literal, and **no state is made with an opacity**: a disabled control has its own tokens, so
  it stays readable.
- **Contrast is a rule that is checked, not a wish.** Text is at least 4.5:1, a disabled control's text at least 3:1 (WCAG
  exempts disabled controls; the catalog does not), an outline and the focus ring at least 3:1, in the light and in the dark
  theme, in every state (default, hover, focus, busy, disabled).
- **Exceptions are explicit.** A control that is not a catalog component carries `data-ui="custom"` and a
  `data-ui-reason`; today three exist (the inline rename of a heading, the lane chip of a dialog, the statistic tiles of the
  Executions page).
- **Enforced by tests.** `tests/e2e/test_ui_catalog.py` builds every variant in every state in both themes and measures the
  contrast of what the browser paints; and it walks the main pages and dialogs in both themes and fails for a button that
  is neither a catalog component nor a declared exception, or that cannot be read. A new page is added to that list.
- **How to extend.** A new variant is added to the catalog stylesheet with its tokens for both themes, a row in the guide
  and an entry in the test's matrix. A third party uses the catalog's classes and tokens and gets the dark theme, the
  states and the contrast for free.

## 3. Consequences

- A theme problem is fixed once, in a token or in the catalog, and cannot reappear per feature; the tests make a regression
  visible at once.
- Designing a new screen is choosing components. Where the catalog lacks something, the cost is a catalog entry (small,
  reviewed, both themes) rather than a local style.
- A few older one-offs were replaced (the purple "Start processing", the filter buttons of the History, the opacity rules
  of disabled controls); the Stop state of that button is the destructive look from the catalog.
- Not decided: a published, versioned package of the catalog for third parties and a living catalog page (the guide and the
  test matrix are the reference today); components other than buttons are listed but not yet covered by contrast tests.

## 4. Addendum: dialogs are sized by their content

The owner's rule, for every screen overlay: **as large as necessary, as small as possible, but cleanly readable.** A dialog
with one select and three buttons had been about 700 px wide because every dialog took the width of the artifact dialog
(or a width of its own in its own stylesheet).

- **One rule in the one dialog definition** (`.modal__panel` in `modal.css`): the panel is `fit-content`, at least
  `--dialog-min-w` (20 rem), at most `--dialog-cap-w` (40 rem) and never wider than the window minus the gutters; form
  controls inside keep a usable width (16 rem). The widths that dialogs had in their own stylesheets (provider, version,
  artifact fields, retention rules, node settings) are gone.
- **Exceptions are named, with a reason, by one mechanism:** `data-dialog-size` (`wide`, `full`, `artifact`) and
  `data-dialog-reason` on the `<dialog>`, set through the `modal()` macro. `wide` and `full` raise the cap only (the dialog
  still shrinks to its content); `artifact` keeps the artifact dialog's own sizing from its content height, with the rail.
- **The list is a test:** `tests/e2e/test_dialog_sizes.py` fails when a dialog is added to or removed from the declared
  exceptions, when one has no reason, when a dialog without an exception is wider than the cap, when a small dialog (name,
  confirmation) is not small and when a dialog does not fit a 360 or 320 px screen.
- **Declared today** (the owner may change any of them): the artifact dialog (`artifact`), the settings of a node, the guard
  window, the retention rules, the artifact fields and an agent version (`wide`). The node settings are declared `wide` only
  for kinds with two columns; an action's settings (one select) are compact all the same, because `wide` raises the cap and
  does not set a width.

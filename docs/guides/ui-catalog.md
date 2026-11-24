# The UI catalog

Every control of the interface comes from one catalog with one definition ([ADR-059](../architecture/adr/059-one-catalog-of-ui-building-blocks.md)).
You pick a component; you do not style a button. This page is the reference for contributors and for anyone who extends
the application (a node kind, a page, later a community add-on): use these classes and tokens and you get the light and the
dark theme, every state and the contrast rules without writing any CSS for them.

## Rules

1. **Use a catalog component.** A `<button>` carries `button`, `icon-button`, `chip-button`, `task-tab`, `nav-link`,
   `menu__item` or `popover__option`. The rare exception carries `data-ui="custom"` and `data-ui-reason="why"`.
2. **No colour in a component.** Colours come from the tokens in `static/css/tokens.css` (`var(--color-text-primary)`,
   `var(--btn-outline-border)` ...), never from a literal. Both themes define the tokens; a component that only uses them
   works in both.
3. **No opacity for a state.** A disabled, busy or inactive control gets its look from tokens, so it stays readable. Do not
   write `opacity: 0.5` on a control.
4. **A new variant goes into the catalog**, not into the feature: add it to `static/css/forms.css` with tokens for both
   themes, a row in the table below and an entry in the matrix of `tests/e2e/test_ui_catalog.py`.
5. **Destructive controls** (delete, discard, clear) add `is-danger` to the catalog component; the solid `button--danger`
   is only for the confirming button of a dialog.

## Buttons

| Component | Class | Use it for |
|---|---|---|
| Primary | `button button--primary` | The one main action of a place: *Edit*, *Comment*, *Save*, *+ Add lane*. |
| Secondary (outlined) | `button button--ghost` | Every other action: *Close*, *Cancel*, *Start processing*, *Retention*. |
| Danger, solid | `button button--danger` | Only the confirming button of a destructive dialog. |
| Danger, outlined | `button button--ghost is-danger` | A visible destructive action in a toolbar: *Clear finished*. |
| Icon only | `icon-button` (small: `icon-button icon-button--sm`) | A command with an icon and no text. It needs an accessible name: `aria-label` (or a visible tooltip name). |
| Icon only, destructive | `icon-button is-danger` | A delete icon: it turns red on hover and focus. |
| Chip (toggle) | `chip-button` with `aria-pressed="true|false"` | A filter or a switch among a few: *All / Comments / Executions / Changes*. |
| Chip (small action) | `chip-button` without `aria-pressed` | A compact action in a tight place, such as *Action* in a stage header. |

Sizes: the default is 2.5 rem high; `button--sm` (and every `.action-row`) is 2 rem. `button--md` brings one button back to
the full size inside a compact container.

```html
<button type="button" class="button button--primary">Save</button>
<button type="button" class="button button--ghost">Close</button>
<button type="button" class="button button--ghost button--sm is-danger">Clear finished</button>
<button type="button" class="icon-button" aria-label="Board options"><!-- icon --></button>
<div role="group" aria-label="Show">
  <button type="button" class="chip-button" aria-pressed="true">All</button>
  <button type="button" class="chip-button" aria-pressed="false">Comments</button>
</div>
```

In a script, the same classes: `button.className = "button button--ghost"`. An icon comes from `icon("name")` in
`static/js/components/icons.js`.

### States

| State | How it is set | Look |
|---|---|---|
| Hover | the pointer | the outlined variants get the tinted fill and the stronger border; the primary gets its hover tone |
| Focus | keyboard focus (`:focus-visible`) | a 2 px ring in the accent colour, 2 px away (global, `base.css`) |
| Busy | `aria-busy="true"` | the cursor shows progress; show a `.spinner` inside (see `forms.css`) |
| Disabled | `disabled` (or `aria-disabled="true"` when it must stay focusable) | one look for every variant: a quiet fill, a visible outline, dimmer but readable text; no hover |

### Contrast rules (checked by a test, light and dark, every state)

| What | Minimum |
|---|---|
| Text of a control | 4.5 : 1 |
| Text of a disabled control | 3 : 1 (stricter than WCAG, which exempts disabled controls) |
| The outline of an outlined variant, and the focus ring | 3 : 1 |

The tokens (all in `tokens.css`; the same formulas in both themes):

| Token | Meaning |
|---|---|
| `--button-primary-bg`, `--button-primary-hover-bg`, `--button-primary-text` | The filled primary button: purple with light text in the light theme, a light lavender with dark text in the dark one |
| `--btn-outline-text`, `--btn-outline-bg`, `--btn-outline-bg-hover` | The outlined variants |
| `--btn-outline-border`, `--btn-outline-border-hover` | Their outline (3 : 1 against the card) |
| `--btn-danger-border` | The outline of the outlined danger variant |
| `--btn-disabled-bg`, `--btn-disabled-text`, `--btn-disabled-border` | The one disabled look |
| `--btn-chip-on-bg` | A pressed chip |
| `--color-pulse` | The highlight of a place the user was taken to (a comment that is jumped to): the accent in the light theme, the sand tone in the dark one |

## Other components that exist

Use these instead of building a new one. They live in `static/js/components/` unless stated.

| Need | Use |
|---|---|
| A dialog | `modal.js` with `templates/components/modal.html`; a question: `confirm-dialog.js`; input fields: `form-dialog.js`; a dialog that runs a request: `action-dialog.js` |
| A tab list | `tabs.js` (`.task-tabs` / `.task-tab`) |
| A menu of commands | `action-menu.js` (`menu__item`) |
| A list to pick from, placed next to its trigger | `lane-picker.js` and `popover.js` (`popover__option`) |
| A short message above a page | `alert-bar.js` with `templates/components/alert.html` |
| An explanation of a field | `info-tip.js` (the (i) that opens a tooltip) |
| An on/off setting | `switch.js` |
| A text edited in place | `inline-name.js` |
| A person or system as a round shaded circle | `avatar.js` (the kind is the icon and the accessible name; `initials` for a person later) |
| The marker of a timeline entry | `tasks/history-marker.js` |
| A chip with a status | `.history-chip` in `history.css` |
| A bar for selected rows | `selection.js` and `bulk-bar.js` |
| A guard against leaving unsaved changes | `leave-guard.js` |
| A collapsible rail or a navigation group | `collapsible-nav.js`, `nav-group.js` |
| A list that is reordered by hand | `sortable.js` |
| Settings that override a default | `settings-group.js`, `override-row.js`, `options-panel.js` |
| Rules with all/any conditions | `rule-builder.js`, `rule-set.js` |
| A `#` reference in a text | `reference-picker.js` |
| An icon | `icons.js` (`icon("name")`), the paths in `templates/components/icons.html` |

## Exceptions that exist today

| Where | Why it is not a catalog component |
|---|---|
| `inline-name.js` (lane names, the name of a pipeline, an agent's identity) | It reads as the heading until it is hovered or focused |
| The lane chip in a dialog header (`modal__subtitle`) | It is tinted with the lane's hue |
| The statistic tiles of the Executions page (`ex-count`) | A tile that filters the list |

## For a third party

Load the application's stylesheets (they are in the page already for anything rendered by the application) and write plain
HTML with the classes above. Do not copy the CSS and do not define colours: a copy would not follow a theme change or a
fix to the catalog. If you need something the catalog does not have, ask for a variant (see the checklist) instead of
styling it yourself.

## Checklist for a change that adds or changes a control

- [ ] The control is a catalog component; if not, a variant is added to `forms.css` (or `components.css`) with tokens for
      both themes.
- [ ] No colour literal and no `opacity` for a state in the change.
- [ ] Icon-only controls have an accessible name.
- [ ] `tests/e2e/test_ui_catalog.py` passes; a new page or dialog is added to its list; a new variant is added to its matrix.
- [ ] You looked at it in the light and in the dark theme.

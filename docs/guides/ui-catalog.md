# The UI catalog

Every control of the interface comes from one catalog with one definition ([ADR-059](../architecture/adr/059-one-catalog-of-ui-building-blocks.md)).
You pick a component; you do not style a button. This page is the reference for contributors and for anyone who extends
the application (a node kind, a page, later a community add-on): use these classes and tokens and you get the light and the
dark theme, every state and the contrast rules without writing any CSS for them.

## Binding rules for every contributor

These rules bind **everyone who changes the interface**, whether a person, a script or an automated tool; the document
does not tell them apart. They are the owner's design decisions ([ADR-059](../architecture/adr/059-one-catalog-of-ui-building-blocks.md) §6),
not suggestions, and a change that breaks one is sent back.

1. **Build modules, not one-offs.** A control (button, switch, chip, menu entry) *and* a section of a window or page (a
   list of rules, a form block, a popup of choices, a header with its actions) is a **reusable component**: one
   definition, used wherever it is needed. If the component you need does not exist, add it to the catalog first and use
   it from there; never write markup or CSS for one feature that another could have used.
2. **Windows are sized by their content.** As wide as necessary, as narrow as possible, but cleanly readable. A window
   does not grow into an endless page to scroll: when there is room its sections sit side by side in a two-column grid,
   and it falls back to one column on a narrow screen. A window that is wider than the default is a named exception.
3. **A window that saves carries its name in its title** (rule 6 below), and its configuration is described as data where
   a description exists (node kinds, ADR-054), so that one renderer lays it out.
   **Every window and every overlay that asks for something is a form manifest** ([ADR-065](../architecture/adr/065-every-window-is-a-form-manifest.md)):
   a YAML file in `ui/forms/`, drawn by `FormView`, with the layout handle so the owner can arrange it himself. A hand-built
   window is only allowed as a named exception with a reason (a question, a display-only window, a picker; the list is in
   `tests/test_window_rule.py`); an existing one is moved when it is touched. Never build the fields of a window by hand.
4. **Colours, states and texts follow the catalog:** tokens only, the states and contrast rules below, the text rule of
   a node. Every new component is covered by the catalog tests in both themes.
5. **Persist on the user's act** (ADR-059 §7): no autosave by interval or keystroke; text on leaving the field or Enter;
   a choice when it changes; never redraw under a focused field. In detail, for the node dialog: a one-line text saves
   on focusout and Enter, a textarea on focusout and Ctrl+Enter (Enter is a new line), a select, switch, checkbox or chip
   once at the moment it changes; there is no save on an `input` event, no debounce timer, no interval. While a text
   field has the focus nothing in its dialog is drawn again (a draw caused by an event waits until the field is left,
   `whenFieldFree`), so the caret and the selection never move. Closing the dialog (X, Escape, backdrop) or switching
   the node saves every field with unsaved text first (`flushDirty`); a field with unsaved text shows the "Not saved"
   marker. The policy is one module, `static/js/editor/persist-policy.js` (pure rules `persistsOn`, `isTextEditing`,
   unit tested); a control of a node dialog uses `bindPersist` / `persistText` and never listens to these events itself.
   **Windows known not to follow the rule yet** (seen, not changed; the owner decides when they are brought in line):
   the executions filter bar (`executions/filter-bar.js`, a filter applied by a keystroke timer, nothing is saved), the
   previews of the guard editor and of the retention dialog (a debounced request per keystroke, nothing is saved), the
   artifact field rail of the task window (`tasks/field-rail.js`, saves on `change`, has no "Not saved" marker and no
   flush on closing), and the forms with their own Save button (providers, credentials, run limits, the agent editor)
   which keep their form state until Save and are outside this rule.
6. **Navigation entries go through `NavigationRegistry`.** No hardcoded `<a href="/settings/...">` in templates,
   no manual `active_nav` strings in routes. Every page registers its entry via
   `registry.register(NavLinkEntry(...))` (see [ADR-066](../architecture/adr/066-modular-navigation.md)).
   A test enforces this (`tests/test_navigation_modularity.py`).

## Rules

1. **Use a catalog component.** A `<button>` carries `button`, `icon-button`, `chip-button`, `ge-switch` (an on/off
   switch, `switch.js`), `task-tab`, `nav-link`, `menu__item`, `popover__option`, `info-tip`, `layout-handle` or `lw-grip`. The rare exception carries `data-ui="custom"` and `data-ui-reason="why"`.
2. **No colour in a component.** Colours come from the tokens in `static/css/tokens.css` (`var(--color-text-primary)`,
   `var(--btn-outline-border)` ...), never from a literal. Both themes define the tokens; a component that only uses them
   works in both.
3. **No opacity for a state.** A disabled, busy or inactive control gets its look from tokens, so it stays readable. Do not
   write `opacity: 0.5` on a control.
4. **A new variant goes into the catalog**, not into the feature: add it to `static/css/forms.css` with tokens for both
   themes, a row in the table below and an entry in the matrix of `tests/e2e/test_ui_catalog.py`.
5. **Destructive controls** (delete, discard, clear) add `is-danger` to the catalog component; the solid `button--danger`
   is only for the confirming button of a dialog.
6. **A window that saves carries the name in its title.** A window with a Save button (where something is created or
   edited, not a display-only window) shows "Kind – NAME" in its title bar with the name as an inline rename
   (`inline-name.js`); there is no separate Name row. A thing that needs a name refuses an empty one with a hint under
   the field. Examples: the retention rule, the guard editor. The windows that do not follow it yet are listed in
   [ADR-059](../architecture/adr/059-one-catalog-of-ui-building-blocks.md) §5.

## Buttons

| Component | Class | Use it for |
|---|---|---|
| Primary | `button button--primary` | The one main action of a place: *Edit*, *Comment*, *Save*, *+ Add lane*. |
| Secondary (outlined) | `button button--ghost` | Every other action: *Close*, *Cancel*, *Start processing*, *Retention*. |
| Danger, solid | `button button--danger` | Only the confirming button of a destructive dialog. |
| Danger, outlined | `button button--ghost is-danger` | A visible destructive action in a toolbar: *Clear finished*. |
| Icon only | `icon-button` (small: `icon-button icon-button--sm`) | A command with an icon and no text. It needs an accessible name: `aria-label` (or a visible tooltip name). |
| Layout handle | `layout-handle` | The pill with nine dots on the top edge of a manifest window (ADR-063): `--layout-accent`, `--layout-accent-hover`, `--layout-on-accent` (a colour family of its own, so it is never taken for a "..." menu). 24 px high, the global focus ring. Its menu is `menu menu--layout`. |
| Layout grip | `lw-grip` | The grip of a section or a field in the arrange view: icon only, coloured `--layout-accent-hover` (5.8:1 on the card), a quiet fill on hover, moves with the pointer or the arrow keys. |
| Icon only, quiet | `icon-button icon-button--quiet icon-button--xs` | An icon with no frame and no fill (24 px hit area, a quiet fill on hover and the global focus ring): the guard shield on a card, a stage header and next to the canvas "+". Needs an accessible name. Colours: `--btn-quiet-text`, `--btn-quiet-text-hover`. |
| Icon only, destructive | `icon-button is-danger` | A delete icon: it turns red on hover and focus. |
| Chip (toggle) | `chip-button` with `aria-pressed="true|false"` | A filter or a switch among a few: *All / Comments / Executions / Changes*. |
| Chip (small action) | `chip-button` without `aria-pressed` | A compact action in a tight place. |

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
| The card of a node in the graph editor | `.ge-node` keyed by `data-behaviour`, coloured by the manifest's `ui.color` (a `--node-<color>` token), icon inline before the text column: no rule per kind, see [extending](extending.md#the-card-the-colour-and-what-a-node-leaves-behind) |
| A dialog | `modal.js` with `templates/components/modal.html`; a question: `confirm-dialog.js`; input fields: `form-dialog.js`; a dialog that runs a request: `action-dialog.js` |
| A tab list | `tabs.js` (`.task-tabs` / `.task-tab`); a tab with `disabled` is a place held for what is not built (greyed, skipped by the keys) |
| A page that manages definitions (list of cards or rows, toolbar, detail panel with tabs) | `management-page.js` (`ManagementPage`, `chip`, `make`), styled by `management.css` (`.mg-*`); see "Management pages" below |
| A long list that hides its middle (the versions of an agent: the newest two and the first stay behind "Show more versions (N)", a dotted vertical line through the button; the hidden ones open and close, `aria-expanded`) | `fold-list.js` (`foldEntries` for the entries, `foldSeparator` for the button), styled by `.fold-separator` in `components.css` |
| A select whose text is never cut (as wide as its longest choice, also in a grid column or a narrow window) | `select-fit.js` (`fitSelect(select, {extra})` sets `--select-min` for `select.field__control[data-fit]`; `fitColumn(table, "--name", selects)` makes a column of selects as wide as the widest) |
| A row of controls in a table that must stay readable when the table is narrow (the inputs of an agent) | **Field group**: `.field-group` on the table (it is its own container: the rows break by the width of the table, not of the window), `.field-group__head` and `.field-group__row` (columns in `--fg-cols`), `.field-group__wide` (takes a whole line when paired: a description), `.field-group__end` (a menu), `.field-group--long` for seven or more elements (breaks earlier). Wide: one line; narrower: pairs (2, 2, 2: two columns, the head goes); narrowest: one column. Defined in `forms.css`; use it for any table of rows with several controls |
| The small picture of a pipeline or an action | `graph-preview.js` (`GraphPreview`, `lazyPreview`) with the layout in `preview-layout.js` (`structureOfGraph`, `structureOfChain`, `layoutPreview`) |
| A long text in a panel (a prompt): its first lines, "Show more", "Copy" | `clamped-text.js` (`new ClampedText({ text, lines, label, empty })`, `.element`); `textContent` only, the frame is `.ct__box`, tokens only |
| Short labels typed as one line | the form widget `tags` (`form-widgets.js`): a list in the values |
| A menu of commands | `action-menu.js` (`menu__item`) |
| A list to pick from, placed next to its trigger | `lane-picker.js` and `popover.js` (`popover__option`) |
| A short message above a page | `alert-bar.js` with `templates/components/alert.html`; `show(message, { tone: "info" })` is the calm look for news that is not an error (what a change did beyond the node); it floats above an open window (popover layer), because a window's backdrop would cover the bar |
| An explanation of a field | `info-tip.js` (the (i) that opens a tooltip) |
| An on/off setting | `switch.js` |
| The legend under text that marks resolved references | `resolved-legend.js` (`new ResolvedLegend()`, `.element` after the text, `.show(visible)`); a closed disclosure with the colour swatch `--color-resolved-ref-bg` (`.resolved-legend__mark`) and the words, no `innerHTML`, no glyph in the text; the marked text itself is `<mark class="resolved-ref">` (`renderResolvedBody` in `tasks/references.js`), shown only while the personal setting *Mark resolved references* is on |
| The add menu of the editor, under the "+" or at a point | `add-menu.js`; `openFrom(point, {types, header, emptyText, onPick})` opens the same menu at the pointer for a line released on the canvas (anchored mode: `is-anchored`, a header line `ge-add__from`, only the given kinds), glue and plan in `connect-menu.js` and `connect-plan.js` |
| Choose one of many by typing | `combobox.js` (a field with a list under it; typing narrows it by name, then by description and keywords; arrow keys, Enter, Escape closes only the list; the list is a popup so a dialog does not clip it; ARIA combobox with `aria-activedescendant`; the pure part is `combobox-model.js`) |
| The form of a configuration window | `form-view.js` draws a form manifest (`ui/forms/*.yaml`, ADR-062): sections in a two-column grid (one column on a narrow window), help in a tooltip, `advanced` fields folded, errors per field; the widgets are `form-widgets.js` (`registerWidget`), the layout rules are `form-plan.js` |
| The handle of a manifest window and its menu | `window-layout.js`: a round `layout-handle` with a 3x3 grid of dots on the top edge of the panel, in the middle (the colour family `--layout-accent`, teal, used by nothing else); its menu is the menu component as `menu--layout` (a coloured top edge and a title). Only windows that are YAML manifests have it (ADR-063) |
| Arranging a window | `layout-arrange.js` draws the structure (areas as dashed outlines, fields as bars, a `lw-grip` each), `layout-model.js` holds the moves (pointer drop and arrow keys, a field into any area, areas of one's own with `addArea`, `renameArea`, `deleteArea`; unit-tested); the banner is `lw-banner`; the tile that adds an area is a `button button--ghost button--sm lw-add`, the title of an own area is an `inline-name`, its bin an `icon-button is-danger`; an empty list shows `lw-hint` ("Drop settings here") |
| A text edited in place | `inline-name.js` (also the name in the title of a window that saves: rule 6) |
| A person or system as a round shaded circle | `avatar.js` (the kind is the icon and the accessible name; `initials` for a person later) |
| The marker of a timeline entry | `tasks/history-marker.js` |
| A chip with a status | `.history-chip` in `history.css` |
| A quiet label that is not a control ("Soon") | `.tag` in `components.css` (`--accent-soft` fill, primary text); in a menu: the `tag` option of `action-menu.js` |
| A bar for selected rows | `selection.js` and `bulk-bar.js` |
| A guard against leaving unsaved changes | `leave-guard.js` |
| A collapsible rail or a navigation group | `collapsible-nav.js`, `nav-group.js` |
| A list that is reordered by hand | `sortable.js` |
| Settings that override a default | `settings-group.js`, `override-row.js`, `options-panel.js` |
| Rules with all/any conditions | `rule-builder.js` (the conditions), `rule-editor.js` (one rule: conditions and what to do), `rule-list.js` (the front door: a row per rule with its switch, name and a line about it, opening, taking out with Undo; data in `rule-list-model.js`) |
| A `#` reference in a text | `reference-picker.js` |
| The guards of a scope: one shield and its popup (names, switch, Detach; "Add a guard"; a group *In the action* on an action card); the popup has two layouts: its two buttons sit side by side, and **stacked** when it opens from a stage header or a card (`what.stack`, class `gd-popover--stack`) | `editor/guards.js` (`shieldButton`), `guards/guard-popover.js` (a `popover` with `popover__option`, `ge-switch` and catalog buttons) |
| An icon | `icons.js` (`icon("name")`), the paths in `templates/components/icons.html`; a node kind's glyph in the menus is its manifest's `menu_icon` (else `ui.icon`) |

## Management pages

The pages of pipelines, actions, agents and guards use ONE frame (ADR-069), so they behave alike: a click selects and shows the panel, a
double click and the pencil open the editor, the bin asks first, the arrows, Home, End, Enter and Delete work on the list.

```js
const page = new ManagementPage(document.querySelector("[data-management]"), {
  name: "actions", label: "Actions", itemKey: (item) => item.id,
  tabs: [{ key: "pipeline", label, icon: "action", match: (item) => item.purpose === "pipeline" }],   // optional
  search: (item) => `${item.name} ${item.description}`, tagsOf: (item) => item.tags,                // both optional
  sorts: [{ key: "name", label: "Name (A-Z)", compare: (a, b) => a.name.localeCompare(b.name) }],
  card: (item, view) => element,           // the content of a card (view "cards") or of a row ("list")
  deleteBlocked: (item) => "why it cannot be deleted" || null,   // optional: the bin is disabled and says why
  panel: { icon: (item) => "action", title: (item) => item.name, chips: (item) => [chip("Draft")],
           tabs: (item) => [{ key: "overview", label, render: (body, item) => {} }, { key: "versions", label, disabled: true, render() {} }] },
  onOpen, onEdit, onDelete,                // each gets the item; the page asks before it deletes
});
page.setItems(items);  page.refreshPanel();
```

The page markup is one `<div data-management>`; the stylesheet is `management.css`. A card shows the picture of its graph with
`lazyPreview(host, () => loadStructure(item))` (drawn when it comes into view); the Graph tab uses `new GraphPreview(host, {structure, typeOf, node: 44})`.
Put the page's own facts in `mg-facts` (a `<dl>`), sections in `mg-section`, chips with `chip(text, {glyph, tone})`. The window that makes or changes an
entry is a form manifest drawn by `ManifestDialog` (ADR-065), opened from the *Properties* button of the panel and from the page's *New* button.

The room of the detail panel is reserved (two thirds entries, one third panel, a quiet `panel.placeholder` line without a selection) so that
the entries do not move when one is selected; the page size ("Per page") is part of the toolbar next to the switch between cards and rows (ADR-069 §6).

## Dialogs are sized by their content

A dialog is **as large as necessary and as small as possible, but cleanly readable**. This holds for every overlay; the
exceptions are named, not implied.

- A dialog shrinks to what it holds, never below `--dialog-min-w` (20 rem), and grows to `--dialog-cap-w` (40 rem);
  beyond that its text wraps and its body scrolls. On a narrow screen it is never wider than the window minus the gutters.
- A form control inside a dialog keeps a usable width (16 rem) so that a dialog with one select is compact, not a sliver.
- A dialog that needs more declares it on its `<dialog>` with `data-dialog-size` and says why in `data-dialog-reason`
  (the `modal()` macro takes `size=` and `reason=`): `wide` (still sized by its content but may grow to 64 rem: columns,
  rule builders, tables), `full` (up to the whole window) or `artifact` (the artifact dialog: a form column and a rail,
  sized once from its content height).
- `tests/e2e/test_dialog_sizes.py` holds the list of declared exceptions. Adding one is a decision that shows up in a diff:
  the test names the dialog and the owner confirms it. Today: the artifact dialog (`artifact`), the dialog of a node's
  settings, the guard window, the retention rules, the artifact fields and an agent version (`wide`).
- Never set a fixed width on a dialog or on a single dialog's CSS: use the two tokens or declare the exception.
- A dialog does not become a long column: its sections are components that sit in a two-column grid where the width allows it
  and stack below that (binding rule 2 above).

## Texts of a node

The settings of a node, its card and its ports are read in a narrow dialog, so their texts are short. One rule for the English
source (`graph/nodes/*.yaml`) and, a quarter longer, for every language (`tests/test_node_texts.py` keeps it; an exception is named there
with its reason, and an exception that is not needed any more is removed):

| Text | Rule |
|------|------|
| Label of a kind or a setting | At most 3 words, no full stop |
| Title of a group of settings | At most 4 words |
| Help (the tooltip of the (i)) | At most 2 sentences and about 220 characters. All of the explanation is here, warnings included: a field shows no explanatory line |
| Placeholder | At most 60 characters; an example, not an instruction |
| Option of a select | At most 3 words (`option_labels` gives a stored value another shown text) |
| Port | At most 2 words |
| Card caption | One line, no sentence; the parts filled in are `{...}` |
| A note under a field (the server's answers excepted) | One sentence |

A value that is long in itself is never shown whole: a row that names what a setting inherits (a prompt of thousands of
characters) shows a one-line preview and the whole text in its tooltip (`preview` in `agents/model.js`).

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

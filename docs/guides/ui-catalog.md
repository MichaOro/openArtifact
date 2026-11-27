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
7. **Flexible icon lists have one rule:** fixed order, only the active entries are shown, never a gap, right-anchored and growing to the left, one hover (see *Flexible icon lists* below).

## Rules

1. **Use a catalog component.** A `<button>` carries `button`, `icon-button`, `chip-button`, `ge-switch` (an on/off
   switch, `switch.js`), `task-tab`, `nav-link`, `menu__item`, `popover__option`, `info-tip`, `layout-handle`, `lw-grip` or `ge-state`. The rare exception carries `data-ui="custom"` and `data-ui-reason="why"`.
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
| Status chip as a trigger | `ge-state` | The mark "Draft" / "v3 published" in the toolbar of the pipeline and action editor (`editor/publication-control.js`, ADR-070 addendum): no chrome of its own, the status chip (tinted pill) and a small arrow; it is a button only while there is something to publish or discard, and opens the popup `pub-popover` (a `popover` with `button--primary` Publish and `button--ghost` Discard draft, an inline `field__error` for a refusal). Hover and open darken the chip; the focus ring is the global one. The guard window uses the same control (ADR-081): it takes the calls (`calls`), the words that differ (`texts`), the element the popup sits in (`popupParent`: a modal window hides what is outside it) and an async `beforeAct` that saves the form first. |
| Icon only, quiet | `icon-button icon-button--quiet icon-button--xs` | An icon with no frame and no fill (24 px hit area, a quiet fill on hover and the global focus ring): the guard shield on a card, a stage header and next to the canvas "+". Needs an accessible name. Colours: `--btn-quiet-text`, `--btn-quiet-text-hover`. |
| Icon only, destructive | `icon-button is-danger` | A delete icon: it turns red on hover and focus. |
| Chip (toggle) | `chip-button` with `aria-pressed="true|false"` | A filter or a switch among a few: *All / Comments / Executions / Changes*. |
| Chip (small action) | `chip-button` without `aria-pressed` | A compact action in a tight place. |
| Flag (mark) | `history-flag` (`components/run-flag.js`: `drawRunFlag`) | A small tinted pill that marks a row: *Dry run* / *Testlauf* next to the execution number in the history (ADR-086), or *Observed* / *Beobachtet* (its own tint, `data-kind="observed"`) for a run of an observed pipeline (ADR-088), which says only that; hidden unless the execution is a dry run or observed. |

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
| A tab list | `tabs.js` (`.task-tabs` / `.task-tab`); a tab with `disabled` is a place held for what is not built (greyed, skipped by the keys). The window of a Trigger uses it for *Inputs* and *Dry run* (`InspectorBlocks.triggerTabs`, ADR-086 addendum); the tab chosen is kept by the editor, not in the address, because the window is not an address. The window of every node that leaves a result uses it for *Settings* and *Mock* (`InspectorBlocks.mockTabs`, ADR-087); a pencil beside the close button and the pin on the card open the Mock tab |
| A list of cards to choose one from | `combobox.js` (the test card of the Dry run tab: options by number and title, the lane as the description; `editor/dry-run-panel.js`) |
| A row of an execution list | `history-row-template` (`components/history_row_template.html`) filled by `HistoryList` (`tasks/history-list.js`): the artifact's History tab and the dry runs in the Trigger window's Dry run tab (no bin there) |
| The status bar in the corner of the editor's canvas: the eye of the observe mode, the shield of the guards and the "+" in a fixed order, an entry only while it is active | `status-bar.js` (a variant of `icon-list.js`: entries with a key, an order and `visible`; the arrangement is `icon-list-model.js`), the popup of an entry is `status-popup.js` (title, facts, note, buttons); the icons `eye` (observing) and `hand` (starts refused) |
| The small icons in the top right corner of a node card: the mock pin and the shield of the guards | `card-icons.js` (`placeCardIcon(card, key, order, element)`; the places are `CARD_ORDER`, a variant of `icon-list.js`, the arrangement is `icon-list-model.js`); the look is the quiet icon button (`icon-button--quiet icon-button--xs`) with its hover | 
| The Back button of the execution page | `execution/back-link.js` (`?from=board`, `executions`, `card:<n>`, `action:<slug>`, `pipeline:<slug>`: a whitelist, never an address); a link to an execution adds it with `withOrigin` (ADR-089) |
| The copy button of a long text: a quiet 24 px icon button in the top right corner of the text block, so a long output, a prompt or the body of a card is copied whole without scrolling | `copy-button.js` (`attachCopy(block, getText?, {always?})` wraps the block in a `.copy-host`; `copyText(text)` is the one place that writes to the clipboard: the Clipboard API, then a hidden field and the copy command, else a plain message); the rules are `copy-model.js` (`shouldOffer`, `blockText`). Used for: the Output and Data blocks of a step (History tab and flow panel), the blocks of an agent step (prompts, answer), the body and title of a card (read view and fields), the prompt fields of the agent page, every multi-line setting of a node window (prompt override, body, code) and the Output and Data of the Mock tab |
| Optional items of a form behind "+ Add" | the Add button with the shared menu (`action-menu.js`), the items in a list of the model (`OPTIONAL_ITEMS` in `editor/dry-run-model.js`), each with a remove control (the test card of the Dry run tab) |
| A page that manages definitions (list of cards or rows, toolbar, detail panel with tabs) | `management-page.js` (`ManagementPage`, `chip`, `make`), styled by `management.css` (`.mg-*`); see "Management pages" below |
| A long list that hides its middle (the versions of an agent: the newest two and the first stay behind "Show more versions (N)", a dotted vertical line through the button; the hidden ones open and close, `aria-expanded`) | `fold-list.js` (`foldEntries` for the entries, `foldSeparator` for the button), styled by `.fold-separator` in `components.css` |
| A select whose text is never cut (as wide as its longest choice, also in a grid column or a narrow window) | `select-fit.js` (`fitSelect(select, {extra})` sets `--select-min` for `select.field__control[data-fit]`; `fitColumn(table, "--name", selects)` makes a column of selects as wide as the widest) |
| A row of controls in a table that must stay readable when the table is narrow (the inputs of an agent) | **Field group**: `.field-group` on the table (it is its own container: the rows break by the width of the table, not of the window), `.field-group__head` and `.field-group__row` (columns in `--fg-cols`), `.field-group__wide` (takes a whole line when paired: a description), `.field-group__end` (a menu), `.field-group--long` for seven or more elements (breaks earlier). Wide: one line; narrower: pairs (2, 2, 2: two columns, the head goes); narrowest: one column. Defined in `forms.css`; use it for any table of rows with several controls |
| The small picture of a pipeline or an action | `graph-preview.js` (`GraphPreview`; `lazyPreview` is in quarantine) with the layout in `preview-layout.js` (`sceneOfGraph`, `layoutScene`: layers from the connections, a frame per stage, every connection drawn once) |
| A long text in a panel (a prompt): its first lines, "Show more", "Copy" | `clamped-text.js` (`new ClampedText({ text, lines, label, empty })`, `.element`); `textContent` only, the frame is `.ct__box`, tokens only |
| A long text field that takes Markdown (the text of an artifact, a comment, a prompt): heading, bold, italic, strikethrough, bullet and numbered list, quote, code, code block, link, Preview | `markdown-bar.js` (`new MarkdownBar(textarea, { hint, renderText })`; the bar sits after the field, `.md-bar`, its buttons are 28 px so the bar is two lines high; `reset()` returns to the field; **the link popup** `.md-link-popup` is part of it: Text and Address, Enter inserts, Escape closes it only, the place is worked out from the popup's own origin because a dialog's blurred backdrop frames fixed children); what its buttons do is `markdown-edit.js` (`toggleWrap`, `toggleList`, `toggleOrdered`, `toggleQuote`, `cycleHeading`, `toggleCodeBlock`, `findLink`, `normalizeAddress`, `linkEdit`, pure); the edit goes through `insertText` so undo works; buttons are `icon-button`s, the Preview is a `switch`; no table and no image button; ADR-077 and its Addendum 1 |
| A long text that is read (a card's text, a comment) | `markdown.js` (`renderMarkdown(text, { renderText, renderLiteral, lists, plain })`: headings, `p`, `strong`/`em`/`del`, `code`, `pre` with a language caption, `blockquote`, `ul`/`ol`/`li`, `table` in a scrolling `.md-table`, `hr`, safe links `a.md-link`, built from text nodes, never `innerHTML`; `safeHref` decides what may be a link; `plain: true` gives the lines of a text without blocks and anchors); with references and marks `renderBody` in `tasks/references.js` (`renderText` makes `#12` links, `renderLiteral` draws code and the words of a link as text with the marks only); `new ClampedText({ markdown: true })` for a panel (cut by the height of its lines); a prompt is shown as written, without it; the look is `.md-bar`, `.md-link-popup`, `.md-preview` and the rules of the readers in `components.css` |
| Short labels typed as one line | the form widget `tags` (`form-widgets.js`): a list in the values |
| A menu of commands | `action-menu.js` (`menu__item`) |
| A list to pick from, placed next to its trigger | `lane-picker.js` and `popover.js` (`popover__option`) |
| A short message above a page | `alert-bar.js` with `templates/components/alert.html`; `show(message, { tone: "info" })` is the calm look for news that is not an error (what a change did beyond the node); it floats above an open window (popover layer), because a window's backdrop would cover the bar |
| An explanation of a field | `info-tip.js` (the (i) that opens a tooltip) |
| What an action does (a button that is already there) | `attachTip(button, text)` of `info-tip.js`: the same tooltip on hover and keyboard focus, `aria-describedby`; no help line under the button |
| An on/off setting | `switch.js` |
| A tick box (Required, an on/off choice with a label) | `checkbox.js` (`new Checkbox({ label, checked, disabled, labelHidden, ariaLabel, onChange })`, `.element`, `.checked`): a native input drawn as a purple filled square with a tick, a soft border when unchecked; `DangerCheckbox` is the specialisation (`static variant`, class `ck--danger`) like `ge-switch--danger`. A bare `<input class="check">` takes the same look where a component is not needed (selection boxes, provider forms). Filter chips stay native toggles |
| The ⋮ menu of a row | `ActionMenu` (`action-menu.js`: items `{label, icon, onSelect, danger}`, `role=menu`) opened by a `.sf__more` button, as in `schema-fields.js` (*Add description*, *Add default value*, *Delete*) |
| The emergency stop and its banner (ADR-076) | `stop-switch.js` (`new StopSwitch(root, confirm, { onChanged, onError })`: the label `STOP` and the switch in its red form `.ge-switch--danger`; off it is the neutral switch, on it takes the red of the trash button; switching on asks in the page's confirm dialog and names the executions it aborts, off asks nothing), `stop-state.js` (the one copy of the state per page: `subscribeStop`, `loadStop`, `setStop`, `followStop`), `stop-banner.js` (the banner at the top centre of every page, `[data-stop-banner]` in `base.html`) |
| A length of time (a wait, a timeout) | `duration-input.js` (`new DurationInput({ milliseconds, onCommit })`, `.element`, `.milliseconds`): a number and a unit (ms, sec, min), kept as milliseconds; the largest unit that divides the value evenly is shown (`duration-model.js`: 3467 ms stays, 90000 ms is 90 sec). Never ask for seconds as a bare number when a person has to convert; see [the setting row](#the-setting-row) |
| A flat list of fields as a schema ([ADR-080](../architecture/adr/080-hand-over-tool.md)) | `schema-fields.js` (`new SchemaFields({ fields, types, limits, max, label, extra, showRequired, decorate, onInput, onSettle })`, `.element`, `.value()`, `.problem()`): one row per field on a grid (handle, name and bin, type and *Required*, description, the values of a choice); the rules are `schema-fields-model.js`, the server's `graph/field_schema.py`. It knows nothing of the node that holds it: the `fields` setting type is `FieldsControl` in `editor/setting-controls.js`, and whatever lets a model answer in a shape mounts the same component (the Hand Over Tool and, in the agent's page and as the node setting `answer_format`, the answer format of an agent, [ADR-085](../architecture/adr/085-answer-format-of-an-agent.md)). `extra` (`"default"` or `"value"`) adds one more text to each row: the default of an input, the value of an output ([ADR-083](../architecture/adr/083-inputs-and-outputs-of-actions.md)); `wide: true` draws one row per field under column heads (the Trigger, Output and Complete windows; `rowPlan` in the model plans the columns), without the text meant for a model, and falls back to the stacked rows below 44 rem (container query); the rows of what a node gives to the inputs it runs are `MappingControl` (`mapping` setting) |
| A size (an output limit) | `size-input.js` (`new SizeInput({ bytes, onCommit })`, `.element`, `.bytes`): a number and a unit (B, KiB, MiB), kept as bytes; the largest unit that divides the value evenly is shown (`size-model.js`: 1500 B stays, 65536 B is 64 KiB); the twin of the duration input ([ADR-075](../architecture/adr/075-execute-command-node.md)) |
| A removable setting in a node's window | the **setting row** (`field(label, control, { end: bin })` in `editor/field.js`, `.field__line`): label, control, bin, never overlapping; see [the setting row](#the-setting-row) |
| The legend under text that marks resolved references | `resolved-legend.js` (`new ResolvedLegend()`, `.element` after the text, `.show(visible)`); a closed disclosure with the colour swatch `--color-resolved-ref-bg` (`.resolved-legend__mark`) and the words, no `innerHTML`, no glyph in the text; the marked text itself is `<mark class="resolved-ref">` (`renderResolvedBody` in `tasks/references.js`), shown only while the personal setting *Mark resolved references* is on |
| The add menu of the editor, under the "+" or at a point | `add-menu.js`; `openFrom(point, {types, header, emptyText, onPick})` opens the same menu at the pointer for a line released on the canvas (anchored mode: `is-anchored`, a header line `ge-add__from`, only the given kinds), glue and plan in `connect-menu.js` and `connect-plan.js` |
| Choose one of many by typing | `combobox.js` (a field with a list under it; typing narrows it by name, then by description and keywords; arrow keys, Enter, Escape closes only the list; the list is a popup so a dialog does not clip it; ARIA combobox with `aria-activedescendant`; the pure part is `combobox-model.js`) |
| The form of a configuration window | `form-view.js` draws a form manifest (`ui/forms/*.yaml`, ADR-062): sections in a two-column grid (one column on a narrow window), help in a tooltip, `advanced` fields folded, errors per field; the widgets are `form-widgets.js` (`registerWidget`), the layout rules are `form-plan.js` |
| A number with a default, and a limit that is off by default | the form widgets `limit` (the field shows the default as its value, typing it back stores nothing, "Reset to default" while another number is stored) and `optional-number` (a switch, and once it is on the number with its unit), `form-widgets.js`; the pure rules are `limit-model.js` (`context.defaults` and `context.on_values` give the numbers; ADR-084 addendum 1) |
| A page of settings in tabs | `tabs.js` with one `FormView` per tab (a section of a form manifest names its `tab`), the tab kept in the address (`#storage`): Settings → Personal |
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
| A list that is reordered by hand | `sortable.js` (a handle per entry; used by the field editor, the inputs of an agent and the sources of a Build Context node) |
| The sources of a Build Context node ([ADR-078](../architecture/adr/078-build-context-node.md)) | the `sources` setting type: `SourcesControl` in `editor/setting-controls.js` (rows with a handle, the name, the options of the source and a bin, a select that adds a source not used yet) with its rules as pure functions in `editor/sources-model.js` |
| Settings that override a default | `settings-group.js`, `override-row.js`, `options-panel.js` |
| Rules with all/any conditions | `rule-builder.js` (the conditions), `rule-editor.js` (one rule: conditions and what to do), `rule-list.js` (the front door: a row per rule with its switch, name and a line about it, opening, taking out with Undo; data in `rule-list-model.js`) |
| A `#` reference in a text | `reference-picker.js` |
| The guards of a scope: one shield and its popup (names, switch, Detach; "Add a guard"; a group *In the action* on an action card); the popup has two layouts: its two buttons sit side by side, and **stacked** when it opens from a stage header or a card (`what.stack`, class `gd-popover--stack`) | `editor/guards.js` (`shieldButton`), `guards/guard-popover.js` (a `popover` with `popover__option`, `ge-switch` and catalog buttons) |
| An icon | `icons.js` (`icon("name")`), the paths in `templates/components/icons.html`; a node kind's glyph in the menus is its manifest's `menu_icon` (else `ui.icon`) |

## The setting row

One row for every removable setting of a node window ([ADR-074](../architecture/adr/074-setting-row-and-durations.md)); a control does not
position its own bin, the row does. For people and for later agents:

1. **Anatomy:** label (with its (i)) above the control, or on the line of the control for a switch; the control in a column that gives way
   (`min-width: 0`); the **end action** (the bin) in a column of its own, fixed width, on the line of the control; messages under the row.
2. **No overlap, by construction:** nothing in a row is positioned absolutely over another thing. Pass the bin as `end` to `field()` /
   `createControl(..., { end })`; a test measures that it starts after the control ends and lies on its line.
3. **A switch** sits on the line of its label; what depends on it shows below only while it is on, and Off keeps the values.
4. **A time is a number and a unit** (`DurationInput`): ms, sec, min, stored as milliseconds, shown in the largest unit that divides the
   value evenly. Nobody converts 3467 ms into seconds.
5. **Defaults** are shown (the added row starts with them and the menu says what applies meanwhile); a setting whose row would otherwise
   show what is not kept is stored when it is added.
6. **Bounds** are the server's and both sides say them in plain words with the reason ("a whole number from 2 to 10"), under the field;
   nothing is sent while a value is wrong.
7. **Taking it away** is one click on the bin, and it also takes away a value saved while the row was still "just added".

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

The page markup is one `<div data-management>`; the stylesheet is `management.css`. A card shows no picture of its graph (too much unrest, ADR-069 §7): the Graph tab of the panel draws it with
`new GraphPreview(host, {scene: sceneOfGraph(detail, isTool), typeOf, node: 44})` (the graph as `GET /api/pipelines|actions/{id}` or one version gives it: nodes with `stage_id`, edges with ports). `lazyPreview(host, () => loadScene(item))` (drawn when it comes into view) is not used any more and is in quarantine.
The toolbar has two rows when the page has tabs: search, order, "Per page" and cards or list on row one, the tabs and the filter on row two; without tabs the filter follows the order on row one.
Put the page's own facts in `mg-facts` (a `<dl>`), sections in `mg-section`, chips with `chip(text, {glyph, tone})`. The window that makes or changes an
entry is a form manifest drawn by `ManifestDialog` (ADR-065), opened from the *Properties* button of the panel and from the page's *New* button.

The room of the detail panel is reserved (two thirds entries, one third panel, a quiet `panel.placeholder` line without a selection) so that
the entries do not move when one is selected; the page size ("Per page") is part of the toolbar next to the switch between cards and rows (ADR-069 §6) and follows the room: the base is the number of whole columns times whole rows that fit the area (at least 12), the choices are the base and twice and four times the base (never over 500), and the browser remembers the step, not the number (ADR-069 §12, `page-size.js`). A page passes no page size. The rows of the archive are two lines (title and number, then the lane the card came from and the day of archiving), set by `data-page="archive"` on the root (ADR-069 §13); the other pages keep their rows.

**Cards** (ADR-069 §9): every card of every management page has one size (19 rem by 11 rem, `--mg-card-w` / `--mg-card-h`; ADR-069 §10) and one arrangement, built by
`cardBody({title, text, chips, facts, date})` of `management-page.js`: the title on top (two lines, then "…", clear of the pencil and the bin), the text in the
middle (two lines, only when there is one), at the bottom one row of chips (never wrapped), one line of facts and the date on the last line. A page never builds its own card markup. The grid is
`repeat(auto-fill, 19rem)` and does not stretch.

**Draft / published mark of an editor** (ADR-069 §9, ADR-070): `editorChip(graph)` of `editor/versions-tab.js`, in the toolbar beside "All pipelines" /
"All actions": "Draft" or "v3 published", following the changes of the editor.

A list that only reads (the archive of the board, ADR-071) passes `readOnly: true`: its entries have no pencil and no bin and a double click opens
nothing. It is `tasks/archive-view.js`, shown by the board's menu entry *Show archive* / *Hide archive*.

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

## Cards of the pipeline view

The cards on the canvas have a size and a title rule, so a column of them looks calm (the owner's decision after a comparison of widths):

- **Sizes:** an **action** card is 228 x 76 px (`ui.size` in `graph/nodes/action.yaml`). The flow cards (agent, code, http, set, github, postgres, sqlite, artifact, context, switch)
  keep the size of their behaviour (250 x 84, an `if` 250 x 104); the plain ones (Trigger, Timer, Complete), the tools and the pipeline card keep theirs too. The ports are placed from the size, so a change of
  a size moves the ports and the edges with it, and the stage's slot heights follow (`slotHeights`).
- **The title reserves two lines, always:** on an action card and on the flow and switch cards the name has a fixed height of two lines (`min-height: 2.3em`, `line-clamp: 2`), so a card does not change its
  height whether the name needs one line or two; a one-line name leaves the second line empty and a longer one is cut with an ellipsis at its end. The kind label (`Action`, the caption of a flow card)
  stands under the title block with a gap of 0.3 rem, so it never touches the second line, used or not. The whole name stays the tooltip (ADR-082).
- **The icon list** (mock pin, shield) lies in the top right corner, beside the title text and not over it: the card keeps its right padding for it and for the port labels.
- Stage cards (their header), tools and the Output card are not part of this rule: their names stay on one line.

## Flexible icon lists

A row of small icons whose members come and go (the corner of the canvas, the corner of a node card) follows **one rule**, so that nobody invents another:

- **Fixed order:** every entry has its own place in the order (`order`), not a slot. A new entry takes its place between the others, never at the end by accident.
- **Only what is active is shown:** an entry that is not active is not in the list at all. With four possible entries of which only the second and the fourth are active, those two sit next to each other: **no gap, no placeholder** for the first and the third.
- **Anchored at the right edge, growing to the left:** the right-most entry (the shield on a card, the "+" in the canvas corner) keeps its place; the others are added on its left.
- **Declarative entries:** an entry is a line (key, order, visibility, icon, label, what a click does); another icon costs one line. One base, `components/icon-list.js` (the pure logic is `icon-list-model.js`), serves every such list; a list is a **variant** of it.
- **One hover:** the icons are quiet icon buttons (`icon-button--quiet`), whose hover tint shows that they can be clicked; no list has its own hover. The glyph sits in the **centre** of a square hit area (24 px on a card, 40 px in the canvas corner): `.icon-button` has no padding of its own (the browser's 1px 6px is wider than the content of a 24 px button and pushed the glyph 3 px to the right); `tests/e2e/test_icon_list_glyphs.py` measures it for every variant, normal and hover.

**One base, thin variants.** `IconList` (`icon-list.js`) holds the entries, the order and the no-gap rule; a variant (`defineVariant` in `icon-list-model.js`) says only what differs: a `name`, the **whitelist** `allow` of the keys the list may show (any other key is refused with an error that names the allowed ones, so a misspelled or foreign key cannot slip in), the **order table** `order` (key to place), what an inactive entry is (`inactive: "hide"` keeps it in the page with `hidden`, `"detach"` takes it out), the data attributes of an entry's element, the CSS class of a button the list makes (the size) and, outside the variant, the **host** (the element the CSS anchors at the right edge: the canvas corner's row, the card's `.ge-node__icons`).

Used now: the status bar of the canvas (eye of the observe mode, stop sign, shield, "+": the variant `STATUS_BAR` in `status-bar.js`) and the node card (skip marker of a dry run, mock pin, shield: the variant `CARD_ICONS` in `card-icons.js`).

**The skip marker** (`components/skip-marker.js`, pure part `skip-marker-model.js`): a node card on the flow page whose step a dry run (or an observed run) skipped shows the *fast forward (two arrows)* icon, the "wind forward" of old recorders, as the first entry of the card's list, left of the mock pin and the shield. Its tooltip says what the node would have done (*Skipped in a dry run: would have waited 3 s*; German *Im Dry run übersprungen: hätte …*). The same icon (small, with that text as its title) stands beside the state of the step in the path list, and a button with the shared tooltip beside the outcome in the step detail of the history. **Dimmed means "not reached":** a skipped node was passed in the flow, so it keeps the look of a node that ran; only a node the run never came to is dimmed and dashed. **The skip marker and the mock pin never meet on a node:** a node that handed over a mock was processed, not skipped, and a step an observed run could not see (`data.not_observable`) has neither.

**The Execution Trace** (the right area of the execution page, `execution/flow-panel.js`; the rounds are `execution/trace-view.js` over the pure `trace-model.js`): three registers with the shared `Tabs`
(*Overview*: path, details, the output of the step; *Trace*: only for an agent step; *Context*: the run context), the chosen one in the address (`#overview`, `#trace`, `#context`) and kept while other
nodes are selected (a node without rounds shows Overview). Trace: the **newest round first**, three shown, *Show N more rounds* (a chunk of twenty), **the first round last** as an anchor; a round is an
accordion row (`details`) that is open while it works or has a failure; a **Live** pill (paused when scrolled away), a search and a filter (all, errors, tool calls). Events are names, states and times, no message texts.

**A third variant** costs: a whitelist and an order table in a `defineVariant` call, a size (the button class), a host element with its anchoring CSS, and one `add` per entry. No new arrangement code.

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

## The copy button

One component copies a long text whole (`components/copy-button.js`); a block that has long text gets it with one line, `attachCopy(block)`.

- **Where it sits:** inside the block, at its top right, 24 x 24 px with the glyph centred (the rule of the icon buttons). The block is wrapped in a `.copy-host`; the host does not scroll, the block
  inside may, so the button **stays in view while a long block scrolls**. A copy button never covers text: the block gets right padding (`.has-copy`) while the button is shown.
- **What it copies:** the full text, not what is visible: the whole output of a step however far it has scrolled, the Markdown of a body as written (not the drawn headings), the pretty-printed JSON of the
  Data block, the current value of a field (also one that is being edited). It copies what the page shows; a masked value is never read.
- **When it is there (the visibility rule, `shouldOffer`):** the text is not empty and has more than one line or at least 80 characters. A short single line (a name, a number, a one-line title) has no
  button: selecting it is quicker. A field the user fills with prose (a prompt, a body, code, the output of a mock) passes `always`: it has the button as soon as it holds something. The button follows the
  text: it appears and disappears as a field is typed in or a block is filled.
- **What it says:** after a click the icon is a tick for 1.5 seconds and its name is "Copied" (announced politely for a screen reader); where the clipboard is not allowed (an insecure page, a denied
  permission) it shows "Copying is not possible here" for a moment instead of failing silently.
- **One writer:** `copyText` is the only code that writes to the clipboard: the text "Copy" buttons of a long text (`clamped-text.js`), of the run context and of the token window use it too.
- **Not in a header:** step headers and status rows have none; the button belongs to a text block.

**The line from a tool to its agent** (`attachmentPath` in `editor/geometry.js`, the same for every tool kind, in the editor and on the flow page): a tool below its agent keeps the short curve from the top of the tool up to the agent's *Tools* port; a tool above or beside it goes round, above both cards, past both on the nearer side and up to the port from underneath. A line never runs through a card (ADR-079, addendum 1).

# ADR-036: UI conventions and lane settings

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md), [ADR-029](029-dialog-system.md)  
**Amended by:** —  
**Implemented in:** migration 0032 (`lanes.style`); `tasks/lanes.py` (`update_lane`, `LANE_STYLES`), `tasks/schemas.py` (`LaneRead.style`, `LaneUpdate`), `api/lanes.py`, `api/v1.py`, `mcp_server.py` (`list_lanes`); `static/css/{tokens,base,forms,components,task-dialog}.css`; `static/js/tasks/{lane-settings,lanes,board}.js`, `components/action-menu.js`; `templates/components/{lane_settings_modal,lane,header,modal}.html`, `templates/index.html`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md), [05.05](../arc42/05-building-block-view/05.05-interfaces.md), [08.04](../arc42/08-cross-cutting-concepts/08.04-board-concepts.md), [12](../arc42/12-glossary.md); guides [concepts](../../guides/concepts.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md)

## 1. Title

One UI language for three kinds of controls, one scrollbar, and a lane's card look as the first lane setting.

## 2. Context

Pages grew their own copies of the same ideas: the purple button was one class, but "Add lane" sat in the page header as a
neutral button; red for deleting existed in four places (the artifact dialog's rail, the card's trash icon, the history rows,
the inspector) with different rules; the lane menu's Delete looked like every other item; scrollbars were the browser's.
Lanes could only be renamed, although a lane such as "Done" should make its cards look finished.

## 3. Decision

- **Three roles of controls, each defined once.**
  - *Primary action* (purple): `button--primary`, used by every control that creates something (New action, New pipeline,
    New artifact type, Add lane) and by the confirming button of a form. Creating buttons sit in an `action-row` at the top
    right of the page content; the page header holds only page-wide things (title, theme toggle, sign out).
  - *Destructive action* (red): the modifier `is-danger` (`forms.css`, tokens `--danger-soft`, `--danger-ring`) on any control
    that deletes or discards. Text buttons and menu items are red at rest, icon buttons (trash) turn red on hover and focus,
    the tint is the same everywhere; disabled stays dimmed. The solid `button--danger` stays for the confirming button of a
    confirmation dialog only. Behaviour behind the control is unchanged.
  - *Neutral*: everything else (`button--ghost`, `icon-button`): selectors such as "All pipelines", the zoom controls, the
    canvas plus. They never turn purple or red by themselves.
- **One scrollbar** (`base.css`): `scrollbar-color: var(--scrollbar-thumb) transparent` on the root, with the `-webkit-` pseudo
  elements as fallback for engines without it; no component styles its own scrollbar.
- **Lane style.** `lanes.style` is `normal` (default) or `finished` (`LANE_STYLES`; migration 0032, `VARCHAR(16) NOT NULL`
  with a `CHECK`). `PUT /api/lanes/{status}` (and `/api/v1`) takes an optional `title` and an optional `style`, at least one
  (`422` otherwise; an unknown style is `422` and lists the valid ones); `LaneRead` carries `style`; the `board.lanes` event
  carries the lane list as before. MCP `list_lanes` shows `style`; MCP stays read only for lanes.
- **Display is CSS only.** The lane element gets `lane--finished` (server-rendered, and applied by `Board.setLanes` for
  live changes). In such a lane the card title is struck through and muted, the card is dimmed (opacity 0.75) and the body
  stays readable. A card dragged into or out of the lane takes the new look at once because nothing is stored on the card.
- **Lane settings dialog.** The lane menu has Rename, Settings, Delete. Settings opens `#lane-settings-modal` on the shared dialog
  base (`Modal`, `ActionDialog`; ADR-029): header "Lane settings" with the lane's name as a chip in its colour, sections
  below (today only "Appearance": the switch "Cards look finished" and a preview of two sample cards copied from the card
  template), footer Cancel and Save (Save is disabled until something changed). Escape, Cancel and the backdrop discard.
  The size follows from the content and does not change when the switch is toggled; a second section is one more
  `settings-section` (or a tab) and is measured once like the artifact dialog.

## 4. Consequences

- New pages follow the three roles instead of inventing styles; a reviewer checks for `button--primary`, `is-danger` and
  the absence of per-page scrollbar rules.
- The thumb colour is a token (`--scrollbar-thumb`) chosen to match the browsers' default grey, because `scrollbar-color`
  needs both colours.
- More lane settings (a second section) need no new migration pattern: another column or a JSON setting, decided then.

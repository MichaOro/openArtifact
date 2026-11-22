# ADR-029: Dialog system

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-010](010-frontend-without-htmx.md) §6  
**Amended by:** —  
**Implemented in:** `static/js/components/{modal,action-dialog,confirm-dialog,form-dialog,tabs}.js`, `static/js/tasks/artifact-dialog.js`, `templates/components/form_modal.html`, `static/css/modal.css`; no migration  
**Affected chapters:** [05.07](../arc42/05-building-block-view/05.07-frontend-dialogs-tabs-and-flow-viewer.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Title

One small hierarchy for all dialogs.

## 2. Context

ADR-010 introduced a modal for creating an artifact. Dialogs for the artifact, deleting, naming and confirming
then repeated the same behaviour: busy state, closing blocked while a request runs, error line, focus.

## 3. Decision

- Hierarchy: `Modal` (native `<dialog>`: focus trap, Escape, overlay click, a stack of open modals) ->
  `ActionDialog` (request lifecycle: busy state, error, close on success) -> `ConfirmDialog` and `FormDialog` ->
  `ArtifactDialog`. A new dialog is markup plus a call; a subclass is written only for a real difference.
- `Tabs` follows the ARIA tabs pattern (roles, `aria-selected`, roving tabindex, arrow keys, Home and End).
- A saved artifact's dialog is sized once when opened: height is the smallest the content needs, at least 560 px
  and at most 90 % of the window, and width follows from the height (ratio 0.62, between the base width of 34.75
  rem and 800 px). View and edit keep that size.
- Conventions: texts "Create", "Save", "Cancel"; field ids `#<dialog>-field-<name>`.

## 4. Consequences

- Dialogs behave the same and the markup comes from shared macros.
- The size is measured once, so content that grows later (a long history) scrolls inside the body.

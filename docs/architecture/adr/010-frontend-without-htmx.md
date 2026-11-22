# ADR-010: Frontend without HTMX — Server-rendered Shell with Vanilla JavaScript

**Status:** Accepted  
**Date:** 2026-11-20  
**Supersedes:** [ADR-004](004-frontend-approach.md)  
**Superseded by:** —  
**Amends:** [ADR-006](006-api-design.md) (HTMX)  
**Amended by:** [ADR-029](029-dialog-system.md) (dialogs)

## 1. Context

ADR-004 chose "HTMX + Jinja2 + Tailwind CSS + Alpine.js". The first real UI (Kanban shell,
WP-UI-01) showed that this stack was never actually adopted:

- HTMX was loaded from a CDN but no `hx-*` attribute was ever used.
- Tailwind CSS and Alpine.js were never added to the repository.
- WebSocket/SSE real-time streaming was never implemented.

The product requires a **smooth, app-like board UI with drag & drop of cards between lanes**.
HTMX is built around swapping server-rendered HTML fragments; it has no model for pointer-driven
interaction, optimistic updates or client-side ordering state. Drag & drop would be written in
plain JavaScript regardless, with HTMX only acting as a transport.

## 2. Decision

HTMX is **removed**. The frontend consists of:

| Concern | Decision |
|---------|----------|
| Page shell | Jinja2 templates (`templates/base.html`, `templates/components/`), served by FastAPI on port 2909 |
| Styling | Hand-written CSS with a central token system (`static/css/tokens.css`), `data-theme` attribute for Light/Dark |
| Interactivity | Small vanilla JavaScript modules in `static/js/` (theme/sidebar state, later board interactions) |
| Build step | None |
| External runtime assets | None — all CSS/JS is served from `/static` (no CDN) |
| Data exchange | JSON REST API (ADR-006). The board loads `GET /api/tasks` via `fetch` and renders cards client-side (`textContent` only); creation uses `POST /api/tasks` |

## 3. Not decided yet

Drag & drop and real-time updates were decided in [ADR-011](011-board-interactions-sse-and-pointer-dnd.md). Still open, to be decided in their own ADR when the work starts:

- **A JS framework (e.g. React):** only if vanilla modules become unmaintainable. Not planned.

## 4. Consequences

- **Easier:** Full control over interaction quality (animations, drag feedback); no hidden framework behaviour; no CDN dependency; strict, simple deployment.
- **More difficult:** Client-side state (card order, optimistic updates) must be structured by us; without a framework, module boundaries and tests need discipline.
- **Risk:** Hand-rolled JS can grow unstructured. Mitigation: ES modules per feature, one state owner per concern (as `theme.js` today), UI tests for each interaction.

## 5. Design system (current state)

- Colour values exist **only** in `static/css/tokens.css`; components use semantic variables (`--color-background`, `--color-surface`, `--color-glass-card`, `--color-border`, `--color-accent`, `--color-text-primary`, `--color-text-secondary`).
- Glassmorphism is expressed through derived tokens (`--glass-bg`, `--glass-border`, `--shadow-card`, `--blur-glass`).
- Light theme **Sand Dune** (warm, cream/sand; no violet atmosphere) and dark theme **Midnight Purple** share the same tokens; the violet accent connects them.
- Theme is persisted in `localStorage` (`openartifact-theme`); first visit follows `prefers-color-scheme`.

## 6. Task creation (first interaction built on this decision)

- **Modal:** native `<dialog>` wrapped by `static/js/components/modal.js` (reusable). Native `showModal()` gives focus trap, inert background and focus restore. Escape is handled at document level, because browsers make the `cancel` event non-cancelable on repeated Escape presses, which would let a user dismiss the dialog while a request is running.
- **Busy state:** buttons use `aria-disabled` instead of `disabled`, otherwise the focused submit button loses focus and keyboard events leave the dialog.
- **Form logic** (`tasks/artifact-dialog.js`), **rendering** (`tasks/board.js`) and **HTTP** (`tasks/api.js`) are separate modules.
- **Data model:** table `tasks` (`id`, `title`, `body`, `status`, `created_at`, `updated_at`) is intentionally independent of `work_items`, which is bound to the not-yet-built project workspace and has a different status set.
- **Semantic error colour:** `--color-danger` was added to the tokens (error text and invalid borders only).

## Update (2026-11-22): dialogs and later tables

The history above is kept. §6 (the first modal, the `tasks` table next to a `work_items` table) describes the first
interaction. The dialog behaviour has since grown into one hierarchy ([ADR-029](029-dialog-system.md)); the `work_items` table and its model
no longer exist ([ADR-032](032-removal-of-the-unused-workspace-model.md)).

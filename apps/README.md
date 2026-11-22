# apps

- `backend/` — the only application. It also serves the web UI from `openartifact/static` and `openartifact/templates` (no separate frontend build; ADR-004 is superseded by ADR-010). See [backend/README.md](backend/README.md).

There is no second application and no shared-library folder; do not add one without an ADR.

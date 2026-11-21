# tools

Development tooling.

- `scripts/` — Automation scripts (setup, migration, backup)
- `linters/` — Linting and formatting configurations (deferred to WP-02)
- `check_quarantine.py` — checks `quarantine.json` (code that is unused and waits 14 days before it is removed); run weekly by `.github/workflows/quarantine.yml`

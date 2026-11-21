# tests

Automated tests live next to the application they test: `apps/backend/tests/`.

| Kind | Location | Run |
|------|----------|-----|
| Unit and API tests | `apps/backend/tests/` | `pytest` (from `apps/backend`) |
| Browser tests (Playwright) | `apps/backend/tests/e2e/` | `pytest -m e2e --browser-channel chrome` |

The browser tests start the application on a free port with a temporary database, so they need
no running instance. They are excluded from the default `pytest` run. Install the browser once
with `playwright install chromium`, or pass `--browser-channel chrome` to use a local Chrome.
CI runs them in the `e2e` job.

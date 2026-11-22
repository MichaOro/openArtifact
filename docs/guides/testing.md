# Testing

Automated tests live next to the application they test, in `apps/backend/tests/`. All commands run from
`apps/backend` after the [development setup](../../README.md#development) (`pip install -e ".[dev]"` or
`uv sync --all-extras`).

| Kind | Location | Run |
|------|----------|-----|
| Unit and API tests | `tests/test_*.py` | `pytest` |
| Browser tests (Playwright) | `tests/e2e/` | `pytest -m e2e` |

## Unit and API tests

```bash
cd apps/backend
pytest                      # everything except the browser tests (addopts: -m 'not e2e')
pytest tests/test_tasks.py  # one file
pytest -k "timer"           # by name
```

The suite covers the services, the API (`TestClient`), the access protection and request hardening
(`test_access.py`, `test_security.py`), the run engine (`test_engine.py`), migrations (`test_migrations.py`,
which also runs `alembic check` so the models cannot drift from the migrations), logging and the lifespan.
`pytest-asyncio` runs in auto mode and warnings are errors (`filterwarnings = error`, with two
deprecation exceptions). The tests migrate a database once per session and copy it; they do not read the
developer's `OPENARTIFACT_*` environment.

### Coverage

```bash
coverage run -m pytest -q && coverage report     # fails below the fail_under value in pyproject.toml
```

Branch coverage is on; `tests/` and `cli.py` are omitted. CI runs the suite once under coverage and uploads
`coverage.xml` as an artifact.

## Browser tests

The browser tests start the application on a free port with a temporary database, so no running instance is
needed. They are excluded from the default run because they are slow and need a browser. Install the
browser once, then run them explicitly:

```bash
playwright install chromium           # once; add --with-deps on a fresh Linux machine
pytest -m e2e                         # headless Chromium
pytest -m e2e --browser-channel chrome   # a locally installed Chrome instead
pytest -m e2e --headed -k dnd         # watch one test
```

Everything below `tests/e2e/` is marked `e2e` by its `conftest.py`; the fixtures there start the server
(`alembic upgrade head`, then uvicorn on `127.0.0.1:<free port>`) and give every test a clean board.
CI runs them in the `e2e` job (`pytest -m e2e --tracing retain-on-failure`) and uploads the traces of failures.

Run the browser tests before a push or a pull request, not after every small change.

## Quality checks

```bash
ruff check .             # lint
ruff format --check .    # formatting (ruff format . fixes it)
mypy .                   # strict type checking
```

CI runs these four steps in order (lint, type check, tests, browser tests); see the [CI/CD guide](CI-CD.md).

## Writing tests

- A new endpoint or rule gets a test next to the existing ones for that area (`tests/test_<area>.py`), through the
  public API (`client` fixture) rather than by calling internals.
- A schema change needs a migration and keeps `tests/test_migrations.py` green.
- A change to what the user sees or does gets a flow in `tests/e2e/` using the helpers in `tests/e2e/helpers.py`.
- Tests never touch the developer's data directory or a real deployment.

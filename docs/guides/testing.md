# Testing

Automated tests live in `tests/` at the repository root. All commands run from the root after the [development setup](../../README.md#development) (`pip install -e ".[dev]"` or
`uv sync --all-extras`).

| Kind | Location | Run | Size (at the time of writing) |
|------|----------|-----|------|
| Unit and API tests | `tests/test_*.py` | `pytest` | about 1,240 tests |
| Browser tests (Playwright) | `tests/e2e/` | `pytest -m e2e` | about 240 tests |

## Layout

```
tests/
├── conftest.py        fixtures of the unit and API tests (settings, template database, client, event spy)
├── helpers.py         builders and waiting helpers shared by the API tests and the browser tests
├── agent_support.py   a local OpenAI-compatible server (FakeLlm) and builders for providers and agents
├── test_<area>.py     one file per area (below)
└── e2e/
    ├── conftest.py    starts a real server on a free port; marks every test below it `e2e`
    ├── helpers.py     the Board page object, builders for pipelines and executions
    └── test_<area>.py browser flows
```

The areas: services and API (`test_tasks.py`, `test_graphs.py`, `test_health.py`, `test_info.py`,
`test_integration.py` for `/api/v1` and MCP), access and hardening (`test_access.py`, `test_security.py`),
the engine (`test_engine.py`, `test_chain.py`, `test_task_target.py`), execution nodes
(`test_code_runner.py`, `test_code_hardening.py`, `test_http_runner.py`, `test_execution_nodes.py`),
credentials (`test_secrets.py`), agents and providers (`test_agent_render.py` and `test_agent_runtime.py` without a
database, `test_agents_api.py`, `test_providers_api.py`, `test_agent_node.py` for runs, `test_agents_misc.py`; a local
stand-in answers like a provider, so no test calls a real one), history (`test_history.py`, `test_history_global.py`,
`test_execution_flow.py`), migrations (`test_migrations.py`, which also runs `alembic check` so the models
cannot drift from the migrations), configuration, logging and the lifespan. The browser tests cover the
board, dialogs, editor, processing, history, executions page, flow view, execution nodes, access and the CSP
(`tests/e2e/test_*.py`).

`test_code_hardening.py` is skipped off Linux (it needs `resource` and `/proc`); the Code node runs without
resource limits elsewhere, and says so in its result.

## Unit and API tests

```bash
pytest                      # everything except the browser tests (addopts: -m 'not e2e')
pytest tests/test_tasks.py  # one file
pytest -k "timer"           # by name
pytest -n auto              # in parallel (pytest-xdist), see below
pytest --durations=15 tests/test_x.py   # the 15 slowest tests: where the time goes
```

Every test has a timeout of 120 s (`pytest-timeout`, `timeout` in `pyproject.toml`), so a hanging test fails
instead of stalling the run; `@pytest.mark.timeout(300)` raises it for one test.

### Running in parallel

`pytest -n auto` (or `-n 4`) distributes the tests over worker processes. It is opt-in: the default stays
serial and CI does not use it. The suite is safe for it: every test has its own `tmp_path`, servers bind port
0, the shared database engine is per process, and the revision templates are built once per run under a lock.
Measured on 10 of the slowest test files (330 tests) on a 4-core machine that was busy with other work
(load 6): 8 min 43 s serial, 4 min 32 s with `-n 4`, all tests passing.

`pytest-asyncio` runs in auto mode and warnings are errors (`filterwarnings = error`, with two deprecation
exceptions): a leaked connection or an unawaited coroutine fails the test that caused it.

### Fixtures and helpers

- **Environment isolation.** An autouse fixture removes every `OPENARTIFACT_*` variable from the environment
  and `Settings(..., _env_file=None)` never reads a `.env`, so a developer's token or data directory cannot
  change a result. A second autouse fixture restores the shared loggers that `create_app` changes, and a
  third disposes the shared database engine before and after each test and collects garbage so that a leaked
  connection warns in the test that leaked it.
- **A migrated database, copied.** The session fixture `_revision_template(revision)` runs
  `alembic upgrade <revision>` once per revision (on the nearest older template that exists) into a file
  that all pytest-xdist workers share, under a file lock. `migrated_settings` copies the `head` template into
  the test's `tmp_path`, so a test costs milliseconds. `at_revision("0012")` does the same for an old
  revision and returns the database path: a migration test seeds data there and runs only the step it is
  about. `unmigrated_settings` gives an empty database plus the environment alembic reads, for the one
  round-trip test (up, down to base, up again).
- **`client`** is a `TestClient` with the real lifespan on that copy. After the test it fails, naming the
  test, if an aiosqlite connection that the test opened is still alive (a run or task that outlives the
  engine). To change settings (Code nodes off,
  private networks on, a token), build the application yourself:
  `TestClient(_create_app(migrated_settings.model_copy(update={...})))` as `test_execution_nodes.py` does.
- **`published`** records everything the application publishes on its event bus.
- **`tests/helpers.py`** has the builders (`post`, `node`, `connect`, `build_pipeline`, `build_definition`,
  `link`, `make_task`, `slow_pipeline`), `bare_settings` and `db_session_context`. The helpers take any client
  with `get/post/patch/delete`, so the same builders serve the in-process tests and the browser tests (an
  `httpx.Client`).

### Waiting

Do not `sleep` for something to happen. Two helpers exist, in order of preference:

1. `wait_for_run(client, task, status, where=...)` subscribes to the application's event bus and awaits the
   `run.updated` events (in-process `TestClient` only). It looks first, so an event that already happened is
   not waited for, and it fails with the run's state when the timeout passes.
2. `wait_until(read, predicate, timeout)` polls for what has no event, at 20 ms steps. In the browser tests
   use Playwright's auto-waiting `expect(...)` and `Board._eventually` rather than fixed delays.

A timer node in an action definition (`slow_pipeline`) is the way to get a run that stays running, so the
test controls the moment it ends by stopping it.

### Mutation-minded tests

Coverage says a line ran, not that a test would notice if it were wrong. When you write a test, ask what
single change to the code it would catch:

- Assert the **value**, not only the status code: the exact message, the stored field, the published event.
- Test **both sides of every boundary**: the limit itself and the value just beyond it (the retention tests
  put an execution exactly on the age limit; the settings tests try the minimum, the maximum and one past each).
- For a rule with two conditions, vary one at a time, so a mutated `and` / `or` fails a test.
- A refusal test must also show that the refused action **did not happen** (nothing stored, nothing
  published).
- Prefer a test through the public API (`client` fixture) over one that calls internals; it survives
  refactoring and catches wiring mistakes.

### Coverage

```bash
coverage run -m pytest -q && coverage report     # fails below fail_under (95) in pyproject.toml
```

Configured in `pyproject.toml`: branch coverage on, `concurrency = ["greenlet", "thread"]` (SQLAlchemy's async
layer switches greenlets; without this every line after an awaited query counts as missed), `source` is the
`openartifact` package, `tests/` and `cli.py` are omitted, `fail_under = 95`. CI runs the suite once under
coverage and uploads `coverage.xml` as an artifact. The browser tests are not part of the coverage figure.

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

Everything below `tests/e2e/` is marked `e2e` by its `conftest.py`. The fixtures there migrate a database
and start uvicorn on `127.0.0.1:<free port>` as a child process, once per session (`base_url`, without an
access token; `secured_url`, with a token, for the access tests). The child gets the shell's environment
minus every `OPENARTIFACT_*` variable. The `api` fixture empties the server before each test (runs stopped,
artifacts, pipelines and action definitions deleted), so tests start from a clean board. The browser is
configured for a 1280 x 800 viewport and the light theme.

CI runs them in the `e2e` job (`pytest -m e2e --tracing retain-on-failure`) and uploads the traces of
failures; open one with `playwright show-trace`.

Run the browser tests before a push or a pull request, not after every small change.

### The suite is slow

The browser suite is the slow part: roughly 12 minutes on a loaded machine (a few minutes less on an idle
one), because each test drives a real browser against a real server and several wait for a timer node or a
process to finish. Work on one area with `-k` or one file, and run the whole suite once before you push. If
a test fails only in the full run, suspect leftover state from the one before it (the `api` fixture should
have cleaned it) or a wait that is a fixed delay instead of a condition.

## Quality checks

```bash
ruff check .             # lint
ruff format --check .    # formatting (ruff format . fixes it)
mypy .                   # strict type checking
```

CI runs a `static` job (JavaScript syntax, relative links in the Markdown files, the quarantine file), then
`lint` (Ruff lint and format check), `type-check` (mypy), `test` (pytest under coverage) and `e2e`
(Playwright) in that order; see the [CI/CD guide](CI-CD.md). Locally, the three commands above and `pytest`
cover the same ground except for the static checks (`python tools/check_links.py`,
`python tools/check_quarantine.py`, and the JavaScript unit tests: `node --test 'tests/js/*.test.mjs'`,
quote the glob; they take a few seconds and need no npm packages).

`tools/test_audit.sh` runs all of it in one go and reports start, end, duration and result per section (about
35 minutes; `--fast` skips coverage and runs the Python tests in parallel). See [tools/README](../../tools/README.md).

## Writing tests

- A new endpoint or rule gets a test next to the existing ones for that area (`tests/test_<area>.py`), through
  the public API (`client` fixture) rather than by calling internals.
- A schema change needs a migration and keeps `tests/test_migrations.py` green.
- A change to what the user sees or does gets a flow in `tests/e2e/` using the helpers in
  `tests/e2e/helpers.py`.
- A new page, dialog or kind of control is added to `tests/e2e/test_ui_catalog.py` (its page list or its variant matrix):
  every button must be a catalog component and readable in both themes ([UI catalog](ui-catalog.md)).
- A new node kind: see [Extending](extending.md#add-a-kind-of-node) for the list of tests.
- Code that runs processes or opens sockets is tested against real processes and a local server (see
  `test_code_runner.py`, `test_http_runner.py`); the SSRF rules are tested with real addresses and a local server;
  only name resolution is replaced (a stub for `_resolve`), so no DNS is needed.
- Tests never touch the developer's data directory or a real deployment, and need no access to the internet.

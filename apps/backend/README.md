# OpenArtifact Backend

Python 3.12 + FastAPI application. It serves the web UI (templates and static files), the browser API, the integration API
(`/api/v1`), the MCP server (`/mcp`) and runs the pipeline engine, all in one process with a SQLite database.

This file is also the package's readme (`pyproject.toml`) and is copied into the Docker build.

## Setup

```bash
cd apps/backend
uv sync --all-extras              # or: pip install -e ".[dev]"  (CI uses pip)
printf 'OPENARTIFACT_DATA_DIR=./.data\nOPENARTIFACT_HOST=127.0.0.1\n' > .env   # /data is not writable on a workstation; the host defaults to 0.0.0.0
uv run alembic upgrade head       # create or migrate the database
uv run openartifact               # http://localhost:2909
```

`.env` in the working directory is read by the settings. Without `uv`, run the commands without the `uv run` prefix. In open
mode (no `OPENARTIFACT_API_TOKEN`) Code nodes are refused; `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true` allows them for local
development only. Conventions, the full check list and the commit style: [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Commands

| Command | Description |
|---------|-------------|
| `uv run openartifact` | Start the server (the one way to start it; also what the Docker image runs) |
| `uv run pytest` | Unit and API tests (browser tests excluded) |
| `uv run pytest -m e2e` | Browser tests; once: `playwright install chromium` |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking (strict) |
| `uv run coverage run -m pytest && uv run coverage report` | Tests with coverage; fails below 95 % (what CI runs) |
| `uv run alembic upgrade head` | Run database migrations |
| `uv run alembic revision --autogenerate -m "msg"` | Create a migration; `alembic check` reports drift between models and migrations |

Details of the tests: [testing guide](../../docs/guides/testing.md).

## Project Structure

```
apps/backend/
├── alembic/ , alembic.ini     # migrations (versions/0001 to the head, currently 0026)
├── tests/                     # unit and API tests; tests/e2e/ browser tests
└── openartifact/
    ├── app.py                 # application factory (create_app), middlewares, lifespan, error handlers
    ├── cli.py                 # `openartifact` entry point (uvicorn)
    ├── config.py              # settings (OPENARTIFACT_*)
    ├── version.py             # the one place the version is written
    ├── security.py            # access token, sign-in session, AccessGate, TokenProtected
    ├── secret_crypto.py       # encryption of stored credentials (key derived from the secret key)
    ├── secret_store.py        # credential store: create, list names, resolve for a run
    ├── secret_refs.py         # secret references in node settings
    ├── database.py            # engine, sessions (new_session, get_db_session)
    ├── exceptions.py          # OpenArtifactError, ArtifactError, ConfigurationError, ...
    ├── events.py              # in-process EventBus (SSE)
    ├── logging_config.py      # logging with secret masking
    ├── mcp_server.py          # MCP server (/mcp), 14 tools
    ├── schemas_common.py      # shared schema types
    ├── models/                # SQLAlchemy models
    ├── tasks/                 # artifacts: service, repository, schemas, lanes
    ├── graph/                 # pipelines and action definitions as graphs: node kinds (node_types), rules, repository
    ├── engine/                # run engine
    │   ├── runner.py, chain.py, snapshot.py, targets.py, schemas.py   # runs, stage and action chaining, frozen snapshot
    │   ├── executors.py       # what each node kind does when it runs
    │   ├── code_runner.py, code_registry.py   # Code nodes: child process, limits, cleanup of leftovers
    │   ├── http_runner.py     # HTTP nodes: request, address checks, size limit
    │   ├── results.py         # step results and outputs
    │   ├── history.py, history_query.py       # execution history: recording, retention, queries (also the global list)
    │   └── flow.py, flow_schemas.py           # replay of an execution over its snapshot: the flow view
    ├── api/                   # routers: tasks, runs, graphs, executions, secrets, events, v1, routes; deps; hardening middlewares
    ├── web/                   # pages, navigation entries, static files
    ├── templates/             # Jinja2 templates
    └── static/                # CSS and JavaScript (no build step)
```

The building blocks are described in [arc42 chapter 5](../../docs/architecture/arc42/05-building-block-view/README.md).

## Configuration

Environment variables with the prefix `OPENARTIFACT_` (also read from `.env`). The complete list with defaults, bounds and
meaning, including the settings for Code and HTTP nodes and the execution history, is the
[configuration reference](../../docs/guides/configuration.md); it is the one place that lists them. The ones to know first:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_API_TOKEN` | *(empty)* | Access token, at least 32 characters. Needed for Code nodes, credentials, `/api/v1` and `/mcp` |
| `OPENARTIFACT_SECRET_KEY` | `change-me-in-production` | Signs the session cookie and encrypts credentials; at least 32 characters once a token is set or credentials are stored. Do not change it later |
| `OPENARTIFACT_HOST` | `0.0.0.0` | Bind address; use `127.0.0.1` on a workstation |
| `OPENARTIFACT_CODE_NODES_ENABLED` | `true` | `false` forbids Code nodes altogether |

## Database

SQLite in WAL mode, one file in `OPENARTIFACT_DATA_DIR` (`openartifact.db`). It stays SQLite for good; PostgreSQL is not a
planned application database and may only come later as a data source through a connector layer (ADR-020). The application
is built for one process: do not run several against one database file.

The file holds the artifacts, the pipeline graphs, the runs, the execution history and the credentials (encrypted with a key
derived from `OPENARTIFACT_SECRET_KEY`). The history grows with every run until the retention policy (default: the newest 50
executions per artifact) deletes the oldest; the application does not run `VACUUM`, so a file keeps its size after deletions.
Back up the file together with the secret key ([operations guide](../../docs/guides/operations.md)).

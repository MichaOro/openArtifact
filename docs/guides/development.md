# Development

OpenArtifact is one Python 3.12 + FastAPI application. It serves the web UI (templates and static files), the browser
API, the integration API (`/api/v1`), the MCP server (`/mcp`) and runs the pipeline engine, all in one process with a
SQLite database. Every command below runs from the repository root.

## Setup

```bash
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
| `uv run pytest` | Unit and API tests (browser tests excluded). The tests of the Postgres node need a real server: set `OA_TEST_POSTGRES_URL` (a role that may create databases, e.g. `postgresql://oa:pw@127.0.0.1:5432/postgres`), or have docker, which starts a throwaway container on a random port; without either they are skipped, saying so |
| `uv run pytest -m e2e` | Browser tests; once: `playwright install chromium` |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking (strict) |
| `uv run coverage run -m pytest && uv run coverage report` | Tests with coverage; fails below 95 % (what CI runs) |
| `uv run alembic upgrade head` | Run database migrations |
| `uv run alembic revision --autogenerate -m "msg"` | Create a migration; `alembic check` reports drift between models and migrations |

Details of the tests: [testing guide](testing.md).

## Project structure

The repository is one Python project: the application and the web UI it serves are one package, there is no separate
frontend build ([ADR-010](../architecture/adr/010-frontend-without-htmx.md), layout: [ADR-038](../architecture/adr/038-repository-layout.md)).

```
.
├── pyproject.toml, alembic.ini     # the package, its tools (ruff, mypy, pytest, coverage), the migration config
├── openartifact/                   # the application package
│   ├── app.py                      # application factory (create_app), middlewares, lifespan, error handlers
│   ├── cli.py                      # `openartifact` entry point (uvicorn)
│   ├── config.py                   # settings (OPENARTIFACT_*)
│   ├── database.py, events.py, exceptions.py, logging_config.py, schemas_common.py, security.py, version.py
│   ├── models/                     # SQLAlchemy models, one module per area (board, graphs, runs, credentials, agents, enums)
│   ├── tasks/                      # artifacts on the board: service, repository, schemas, lanes
│   ├── artifact_types/             # artifact types and their typed parameters
│   ├── graph/                      # pipelines and action definitions: node kinds, rules, repository
│   ├── engine/                     # the run engine: walk, snapshot, executors, Code and HTTP runners, history, flow replay
│   ├── agents/                     # agents, LLM providers, prompt rendering, the runtime of the Agent node
│   ├── credentials/                # the credential store: encryption, store, ${secret:NAME} references and masking
│   ├── api/                        # interfaces: browser API, /api/v1, MCP (api/mcp.py), SSE, request hardening
│   ├── web/                        # HTML pages, navigation entries, static file serving
│   ├── templates/                  # Jinja2 templates
│   └── static/                     # CSS and JavaScript ES modules (no build step)
├── alembic/versions/               # migrations 0001 to the head
├── tests/                          # unit and API tests; tests/e2e/ browser tests; tests/js/ tests of the pure JS modules
├── docs/                           # guides, arc42, ADRs
├── deploy/, Dockerfile, scripts/   # Docker Compose deployment, image, container entrypoint
└── tools/                          # repository checks (Markdown links, quarantine, container smoke test)
```

The building blocks are described in [arc42 chapter 5](../architecture/arc42/05-building-block-view/README.md).

## Configuration

Environment variables with the prefix `OPENARTIFACT_` (also read from `.env`). The complete list with defaults, bounds and
meaning, including the settings for Code and HTTP nodes and the execution history, is the
[configuration reference](configuration.md); it is the one place that lists them. The ones to know first:

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
executions per artifact) deletes the oldest. The database runs with `auto_vacuum = FULL`, so deleted rows give their space
back to the file system ([ADR-005](../architecture/adr/005-database-persistence.md), update of 2026-11-22).
Back up the file together with the secret key ([operations guide](operations.md)).

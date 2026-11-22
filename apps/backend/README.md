# OpenArtifact Backend

Python 3.12 + FastAPI application. It serves the web UI (templates and static files), the browser API, the integration API
(`/api/v1`), the MCP server (`/mcp`) and runs the pipeline engine, all in one process with a SQLite database.

This file is also the package's readme (`pyproject.toml`) and is copied into the Docker build.

## Setup

```bash
cd apps/backend
uv sync --all-extras              # or: pip install -e ".[dev]"  (CI uses pip)
echo 'OPENARTIFACT_DATA_DIR=./.data' > .env    # the default, /data, is not writable on a workstation
uv run alembic upgrade head       # create or migrate the database
uv run openartifact               # http://localhost:2909
```

`.env` in the working directory is read by the settings. Without `uv`, run the commands without the `uv run` prefix.

## Commands

| Command | Description |
|---------|-------------|
| `uv run openartifact` | Start the server (the one way to start it; also what the Docker image runs) |
| `uv run pytest` | Unit and API tests (browser tests excluded) |
| `uv run pytest -m e2e` | Browser tests; once: `playwright install chromium` |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking (strict) |
| `uv run coverage run -m pytest && uv run coverage report` | Tests with coverage |
| `uv run alembic upgrade head` | Run database migrations |
| `uv run alembic revision --autogenerate -m "msg"` | Create a migration; `alembic check` reports drift between models and migrations |

Details of the tests: [testing guide](../../docs/guides/testing.md).

## Project Structure

```
apps/backend/
├── alembic/ , alembic.ini     # migrations (versions/0001 to head)
├── tests/                     # unit and API tests; tests/e2e/ browser tests
└── openartifact/
    ├── app.py                 # application factory (create_app), middlewares, lifespan, error handlers
    ├── cli.py                 # `openartifact` entry point (uvicorn)
    ├── config.py              # settings (OPENARTIFACT_*)
    ├── version.py             # the one place the version is written
    ├── security.py            # access token, sign-in session, AccessGate, TokenProtected
    ├── database.py            # engine, sessions (new_session, get_db_session)
    ├── exceptions.py          # OpenArtifactError, ArtifactError, ConfigurationError, ...
    ├── events.py              # in-process EventBus (SSE)
    ├── logging_config.py      # logging with secret masking
    ├── mcp_server.py          # MCP server (/mcp)
    ├── schemas_common.py      # shared schema types
    ├── models/                # SQLAlchemy models
    ├── tasks/                 # artifacts: service, repository, schemas, lanes
    ├── graph/                 # pipelines and action definitions as graphs: node kinds, rules, repository
    ├── engine/                # run engine: runner, chain, snapshot, targets, schemas
    ├── api/                   # routers (tasks, runs, graphs, events, v1, routes), deps, hardening middlewares
    ├── web/                   # pages, navigation entries, static files
    ├── templates/             # Jinja2 templates
    ├── static/                # CSS and JavaScript (no build step)
    └── repositories/          # Project/WorkItem repositories: unused, quarantined
```

The building blocks are described in [arc42 chapter 5](../../docs/architecture/arc42/05-building-block-view/README.md).

## Configuration

Environment variables with the prefix `OPENARTIFACT_`. The complete list with defaults and meaning is the
[configuration reference](../../docs/guides/configuration.md). The security-relevant ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_API_TOKEN` | *(empty)* | Access token, at least 32 characters; with it the whole application asks for it. Empty: pages open, `/api/v1` and `/mcp` closed |
| `OPENARTIFACT_SECRET_KEY` | `change-me-in-production` | Signs the session cookie. Enforced: with a token set the application refuses to start with an empty or default key |
| `OPENARTIFACT_ALLOWED_HOSTS` | *(empty)* | Allowed `Host` names, comma separated (`*.example.com`); empty: no check; `/health` exempt |
| `OPENARTIFACT_COOKIE_SECURE` | `auto` | `auto`, `true` or `false` |
| `OPENARTIFACT_MAX_REQUEST_BYTES` | `1048576` | Largest request body |
| `OPENARTIFACT_MAX_CONCURRENT_RUNS` | `8` | Active runs; more gets `429` |
| `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` | `50` | Open event streams; more gets `503` |
| `OPENARTIFACT_CSP_SCRIPT_UNSAFE_INLINE` | `false` | Opt-out only; the default policy is `script-src 'self'` |

## Database

SQLite in WAL mode, one file in `OPENARTIFACT_DATA_DIR` (`openartifact.db`). It stays SQLite for good; PostgreSQL is not a
planned application database and may only come later as a data source through a connector layer (ADR-020). The application
is built for one process: do not run several against one database file.

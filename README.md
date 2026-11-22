# OpenArtifact

**OpenArtifact** is an open-source platform for orchestrating projects, pipelines, and AI agents around structured artifacts. It connects autonomous execution, deterministic processes, and human oversight in one extensible system.

## Vision

A platform where human intent and AI capability converge through **artifacts** — structured, versioned, and traceable units of work that serve as the single source of truth across the entire lifecycle of a project.

## Core Principles

1. **Artifact-first** — Every significant piece of work is an artifact with a defined schema, lifecycle, and traceability.
2. **Deterministic orchestration** — Pipelines execute according to explicit, version-controlled definitions.
3. **Human oversight** — Autonomous agents operate within guardrails; humans remain in the loop at meaningful decision points.
4. **Extensibility** — Pluggable agents, connectors, and artifact types. The platform grows with your needs.
5. **Transparency** — Every action is traceable. Decisions, runs, and results are auditable.

## Quick Start — Docker

```bash
# 1. Clone the repository
git clone https://github.com/MichaOro/openArtifact.git
cd openArtifact

# 2. Configure (required: the compose file reads deploy/.env)
cp deploy/.env.example deploy/.env
#    Set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY, each with: openssl rand -hex 32
#    (with a token the whole application asks for it; see "Access protection" below)

# 3. Build and start
docker compose -f deploy/docker-compose.yml up -d --build

# 4. Open http://localhost:2909 and sign in with the token

# 5. Check health (the state shows "healthy" after the start period)
docker compose -f deploy/docker-compose.yml ps
curl http://localhost:2909/health

# 6. Stop (the data stays)
docker compose -f deploy/docker-compose.yml down
```

The container is published on `127.0.0.1` only; `OPENARTIFACT_BIND=0.0.0.0` opens it to the network, and
[Run behind a reverse proxy](docs/guides/reverse-proxy.md) describes TLS.

### Docker Compose Commands

| Action | Command |
|--------|---------|
| Start | `docker compose -f deploy/docker-compose.yml up -d` |
| Stop | `docker compose -f deploy/docker-compose.yml down` |
| View logs | `docker compose -f deploy/docker-compose.yml logs -f` |
| Check health | `docker compose -f deploy/docker-compose.yml ps` |
| Update from source | `git pull && docker compose -f deploy/docker-compose.yml up -d --build` |
| Update a released image | `docker compose -f deploy/docker-compose.yml pull && docker compose -f deploy/docker-compose.yml up -d` |
| Backup and restore | [Operate the Docker deployment](docs/guides/operations.md) |

**Important:** `docker compose down` does **not** delete persistent data. The `openartifact-data` volume survives. Use
`docker compose down -v` only to remove it. Back up before every update.

### Access protection

With `OPENARTIFACT_API_TOKEN` set, browsers get a sign-in page and scripts and agents send
`Authorization: Bearer <token>` (also for the integration API `/api/v1` and the MCP server `/mcp`). Without a token the pages
and the browser API are open to everyone who can reach the port, and `/api/v1` and `/mcp` are closed. The application refuses
to start with a token shorter than 32 characters or without a secret key of your own. Details and `curl` and MCP examples:
[Sign in and use the API and MCP](docs/guides/integration.md).

### Configuration

Every setting is an `OPENARTIFACT_*` environment variable (in Docker: `deploy/.env`). The complete list with defaults is the
[configuration reference](docs/guides/configuration.md); the ones you will touch first:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_API_TOKEN` | *(empty)* | Access token, at least 32 characters; set it |
| `OPENARTIFACT_SECRET_KEY` | *(change me)* | Signs the session cookie; required once a token is set |
| `OPENARTIFACT_ALLOWED_HOSTS` | *(empty)* | Host names the application answers to (empty: no check) |
| `OPENARTIFACT_COOKIE_SECURE` | `auto` | `true` behind a TLS proxy |
| `OPENARTIFACT_BIND` / `OPENARTIFACT_PUBLISHED_PORT` | `127.0.0.1` / `2909` | Compose only: where the container is published |
| `OPENARTIFACT_LOG_LEVEL` | `INFO` | Logging verbosity |

## Development

### Setup

```bash
# 1. Navigate to the backend project
cd apps/backend

# 2. Install the dependencies (uv, or pip as CI does)
uv sync --all-extras          # or: pip install -e ".[dev]"

# 3. Keep the data local; /data (the default) is not writable on a workstation
echo 'OPENARTIFACT_DATA_DIR=./.data' > .env

# 4. Create the database
uv run alembic upgrade head

# 5. Run the application: http://localhost:2909
uv run openartifact
```

Without `uv`, run the same commands without the `uv run` prefix inside your virtual environment.

### Quality Commands

| Command | Description |
|---------|-------------|
| `uv run pytest` | Unit and API tests (browser tests excluded) |
| `uv run pytest -m e2e` | Browser tests (once: `playwright install chromium`); see [Testing](docs/guides/testing.md) |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking |
| `uv run coverage run -m pytest && uv run coverage report` | Tests with coverage |

### Database Migrations

```bash
cd apps/backend

# Create a new migration after modifying models (then check it with: alembic check)
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1

# Show current schema version
uv run alembic current
```

Contributing: see [CONTRIBUTING](.github/CONTRIBUTING.md).

## Documentation

- **Index:** [docs/README.md](docs/README.md)
- **Guides:** [configuration](docs/guides/configuration.md), [API and MCP](docs/guides/integration.md), [operations](docs/guides/operations.md), [reverse proxy](docs/guides/reverse-proxy.md), [extending](docs/guides/extending.md), [testing](docs/guides/testing.md), [CI/CD](docs/guides/CI-CD.md)
- **Architecture (arc42):** [docs/architecture/arc42/](docs/architecture/arc42/) — 12 chapters; what is built and what is planned: [chapter 4](docs/architecture/arc42/04-solution-strategy.md#43-built-and-planned); known limitations: [chapter 11](docs/architecture/arc42/11-risks-and-technical-debt.md)
- **Architecture Decision Records:** [docs/architecture/adr/](docs/architecture/adr/)

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| Backend | FastAPI + Pydantic v2 |
| Frontend | Jinja2 + CSS design tokens + vanilla JS (no build step) |
| Database | SQLite (WAL mode), for good; PostgreSQL may come later as a data source, not as the application database |
| Migration | Alembic |
| Execution | In-process `asyncio` run engine |
| Interfaces | Web UI, REST (`/api`, `/api/v1`), MCP (`/mcp`), server-sent events |
| Deployment | Docker + Docker Compose (one container, one volume) |

## Status

Pre-release (version `0.1.0`). The artifact board, the pipeline and action editor, the run engine, the integration API, the
MCP server and the access protection are built; the roadmap and the known limitations are in
[arc42 chapter 4.3](docs/architecture/arc42/04-solution-strategy.md#43-built-and-planned) and
[chapter 11](docs/architecture/arc42/11-risks-and-technical-debt.md). The bootstrap phase is tagged `bootstrap-complete`; product
work happens on feature branches.

## License

OpenArtifact is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome. Read [CONTRIBUTING](.github/CONTRIBUTING.md) and the architecture documentation before proposing changes to the core system.

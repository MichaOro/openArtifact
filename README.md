# OpenArtifact

**OpenArtifact** is an open-source platform for orchestrating projects, workflows, and AI agents around structured artifacts. It connects autonomous execution, deterministic processes, and human oversight in one extensible system.

## Vision

A platform where human intent and AI capability converge through **artifacts** — structured, versioned, and traceable units of work that serve as the single source of truth across the entire lifecycle of a project.

## Core Principles

1. **Artifact-first** — Every significant piece of work is an artifact with a defined schema, lifecycle, and traceability.
2. **Deterministic orchestration** — Workflows execute according to explicit, version-controlled definitions.
3. **Human oversight** — Autonomous agents operate within guardrails; humans remain in the loop at meaningful decision points.
4. **Extensibility** — Pluggable agents, connectors, and artifact types. The platform grows with your needs.
5. **Transparency** — Every action is traceable. Decisions, runs, and results are auditable.

## Quick Start — Docker

The fastest way to get started is via Docker Compose:

```bash
# 1. Clone the repository
git clone https://github.com/MichaOro/openArtifact.git
cd openArtifact

# 2. Configure environment (optional — defaults work fine)
cp deploy/.env.example .env

# 3. Start the application
docker compose -f deploy/docker-compose.yml up -d

# 4. Open in browser
# http://localhost:2909

# 5. Check health
curl http://localhost:2909/health

# 6. Stop the application
docker compose -f deploy/docker-compose.yml down
```

### Docker Compose Commands

| Action | Command |
|--------|---------|
| Start | `docker compose -f deploy/docker-compose.yml up -d` |
| Stop | `docker compose -f deploy/docker-compose.yml down` |
| View logs | `docker compose -f deploy/docker-compose.yml logs -f` |
| Check health | `docker inspect --format='{{.State.Health.Status}}' openartifact` |
| Update image | `docker compose -f deploy/docker-compose.yml pull && docker compose -f deploy/docker-compose.yml up -d` |
| Backup DB | `docker run --rm -v openartifact-data:/data -v $(pwd):/backup alpine cp /data/openartifact.db /backup/` |

**Important:** `docker compose down` does **not** delete persistent data. The `/data` volume survives. Use `docker compose down -v` only to remove persistent data.

### Docker Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_HOST` | `0.0.0.0` | Bind address |
| `OPENARTIFACT_PORT` | `2909` | Application port |
| `OPENARTIFACT_DEBUG` | `false` | Debug mode |
| `OPENARTIFACT_DATA_DIR` | `/data` | Database directory (Docker volume) |
| `OPENARTIFACT_DATABASE_FILENAME` | `openartifact.db` | Database filename |
| `OPENARTIFACT_SECRET_KEY` | *(change me)* | Application signing key |
| `OPENARTIFACT_LOG_LEVEL` | `INFO` | Logging verbosity |

## Development

### Setup

```bash
# 1. Navigate to the backend project
cd apps/backend

# 2. Install dependencies (requires uv)
uv sync --all-extras

# 3. Run the application
uv run openartifact

# 4. The server starts on http://localhost:2909
```

### Quality Commands

| Command | Description |
|---------|-------------|
| `uv run pytest` | Run test suite |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking |
| `uv run coverage run -m pytest && coverage report` | Tests with coverage |

### Database Migrations

```bash
cd apps/backend

# Create a new migration after modifying models
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1

# Show current schema version
uv run alembic current
```

## Architecture

- **arc42 documentation:** [docs/architecture/arc42/](docs/architecture/arc42/) — 12-chapter architecture documentation
- **Architecture Decision Records:** [docs/architecture/adr/](docs/architecture/adr/) — Numbered ADRs
- **Diagram directory:** [docs/architecture/diagrams/](docs/architecture/diagrams/) — Architecture diagrams
- **Documentation conventions:** [docs/README.md](docs/README.md)

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| Backend | FastAPI + Pydantic v2 |
| Frontend | Jinja2 + CSS design tokens + vanilla JS (no build step) |
| Database | SQLite (WAL mode) |
| Migration | Alembic |
| Deployment | Docker + Docker Compose |

## Roadmap

> **Bootstrap phase complete** (git tag `bootstrap-complete`). Product development now happens on feature branches, e.g. `feat/kanban-cards`. The work package numbers below are the original bootstrap plan and are not updated per feature.

| Phase | Work Package | Status |
|-------|--------------|--------|
| WP-00 | Repository bootstrap, architecture documentation | ✅ Done |
| WP-01 | Define technical foundation and technology decisions | ✅ Done |
| WP-02 | Python project foundation and development tooling | ✅ Done |
| WP-03 | Self-hosted application runtime | ✅ Done |
| WP-04 | Persistent storage and database migrations | ✅ Done |
| WP-05 | Docker deployment and all-in-one distribution | ✅ Done |
| WP-06 | Core artifact model and domain types | ⏳ Planned |
| WP-07 | Workflow orchestration engine | ⏳ Planned |
| WP-08 | AI agent integration framework | ⏳ Planned |
| WP-09 | Human oversight and review mechanisms | ⏳ Planned |
| WP-10 | External integrations | ⏳ Planned |

## License

OpenArtifact is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome. Please read the architecture documentation before proposing changes to the core system.

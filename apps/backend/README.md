# OpenArtifact Backend

Python 3.12 + FastAPI application.

## Setup

Install dependencies:

```bash
cd apps/backend
uv sync --all-extras
# or: pip install -e ".[dev]"
```

## Commands

| Command | Description |
|---------|-------------|
| `uv run openartifact` | Start development server |
| `uv run pytest` | Run test suite |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking |
| `uv run coverage run -m pytest && coverage report` | Run tests with coverage |
| `uv run alembic upgrade head` | Run database migrations |
| `uv run alembic revision --autogenerate -m "msg"` | Create new migration |

## Project Structure

```
openartifact/
├── __init__.py          # Package entry
├── app.py               # Application factory
├── cli.py               # CLI entry point
├── config.py            # Settings (env-based)
├── database.py          # SQLAlchemy engine & session
├── exceptions.py        # Custom exception hierarchy
├── logging_config.py    # Structured logging setup
├── models/              # Domain models (WP-06+)
├── api/                 # API endpoints (WP-03)
├── web/                 # Web routes (WP-03)
├── templates/           # Jinja2 HTML templates (WP-03)
├── static/              # Static assets (WP-03)
├── graph/               # Pipelines and action definitions stored as graphs (node kinds, rules)
├── engine/              # Execution engine: runs an artifact through a pipeline
└── tests/               # Test suite
```

## Configuration

Environment variables (prefix `OPENARTIFACT_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_HOST` | `0.0.0.0` | Bind address |
| `OPENARTIFACT_PORT` | `2909` | Application port |
| `OPENARTIFACT_DEBUG` | `false` | Debug mode |
| `OPENARTIFACT_DATA_DIR` | `/data` | Database directory |
| `OPENARTIFACT_DATABASE_FILENAME` | `openartifact.db` | Database filename |
| `OPENARTIFACT_SECRET_KEY` | *(required)* | Application signing key |
| `OPENARTIFACT_LOG_LEVEL` | `INFO` | Logging verbosity |

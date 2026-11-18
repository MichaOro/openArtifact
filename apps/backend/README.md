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
| `uv run pytest` | Run test suite |
| `uv run ruff check .` | Lint code |
| `uv run ruff format --check .` | Check formatting |
| `uv run mypy .` | Type checking |
| `uv run coverage run -m pytest && coverage report` | Run tests with coverage |

## Project Structure

```
openartifact/
├── __init__.py          # Package entry
├── config.py            # Settings (env-based)
├── database.py          # SQLAlchemy engine & session
├── exceptions.py        # Custom exception hierarchy
├── logging_config.py    # Structured logging setup
├── models/              # Domain models (WP-02+)
├── api/                 # API endpoints (WP-03+)
├── workflow/            # Workflow engine (WP-03+)
├── templates/           # Jinja2 templates (WP-03+)
├── static/              # Static assets (WP-03+)
└── tests/               # Test suite
```

## Configuration

Environment variables (prefix `OPENARTIFACT_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENARTIFACT_HOST` | `0.0.0.0` | Bind address |
| `OPENARTIFACT_PORT` | `2909` | Application port |
| `OPENARTIFACT_DEBUG` | `false` | Debug mode |
| `OPENARTIFACT_DATABASE_URL` | `sqlite+aiosqlite:///./openartifact.db` | Database URL |
| `OPENARTIFACT_SECRET_KEY` | *(required)* | Application signing key |
| `OPENARTIFACT_LOG_LEVEL` | `INFO` | Logging verbosity |
| `OPENARTIFACT_DATA_DIR` | `/data` | Application data directory |

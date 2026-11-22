# Contributing to OpenArtifact

Thank you for your interest in OpenArtifact. This guide covers setup, the checks to run and the conventions to follow.

## Workflow

1. **Fork and clone** the repository
2. **Create a branch** for your changes
3. **Implement** your feature or fix, with tests
4. **Run the local checks** below before committing
5. **Open a Pull Request** targeting `main`
6. **CI runs automatically** — all checks must pass
7. **Address review feedback**

## Setup

```bash
cd apps/backend
uv sync --all-extras                      # or: pip install -e ".[dev]"  (CI uses pip)
echo 'OPENARTIFACT_DATA_DIR=./.data' > .env   # /data, the default, is not writable on a workstation
uv run alembic upgrade head               # create the database
uv run openartifact                       # http://localhost:2909
```

Without `uv`, drop the `uv run` prefix inside your virtual environment. The browser tests need a browser once:
`playwright install chromium`.

## Local Quality Checks

Run these from `apps/backend` before opening a PR; CI runs the same:

```bash
ruff check .                  # 1. lint
ruff format --check .         # 2. formatting (ruff format . fixes it)
mypy .                        # 3. strict type checking
pytest                        # 4. unit and API tests
coverage run -m pytest -q && coverage report    # 5. coverage (fails below the fail_under value in pyproject.toml)
pytest -m e2e                 # 6. browser tests, slow: before a push or PR
```

All checks must pass. Details, the browser-test fixtures and where tests live: [testing guide](../docs/guides/testing.md).
A change to the models needs an Alembic migration; `alembic check` (run by `tests/test_migrations.py`) fails on drift.

## Vocabulary

The product says **pipeline**, **stage**, **action** (made of execution nodes) and **artifact**. In the code and the API an
artifact is still a `task`, and pipelines and action definitions are stored as a **graph**. Never write **"workflow"**
in new code, UI text or documentation (ADR-015). User-facing text says "artifact", not "task".

## Unused code: quarantine

Do not leave dead code behind and do not delete it blindly. Add an entry to `quarantine.json` (what, where, since when, a
regular expression `usage` that matches *calls*, not the definition; an optional `ignore` array of path globs for files
that must not count, such as tests). `tools/check_quarantine.py` (weekly in CI, or `python tools/check_quarantine.py`) fails
once an entry has had no calls for 14 days: then remove the code and the entry. See ADR-014 §3.6 and [tools/README.md](../tools/README.md).

## Code and comments

- Type-annotated Python 3.12 (`mypy --strict`), `ruff` for lint and format (line length 100).
- Keep comments few and valuable: say why, not what.
- No secrets in code, tests or logs; configuration is `OPENARTIFACT_*` environment variables ([reference](../docs/guides/configuration.md)).
- No inline scripts in templates (the Content-Security-Policy is `script-src 'self'`); colours only as tokens in `tokens.css`.
- New node kinds and navigation entries: follow the [extending guide](../docs/guides/extending.md).

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

feat(backend): add user authentication
docs(architecture): update arc42 Chapter 5
fix(runtime): handle null config values
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

## Branch Strategy

- `main` — stable development branch; PRs target it
- Feature branches — `<type>/<short-name>`, for example `feat/kanban-cards`, `fix/session-expiry`

## Architecture Documentation

Significant changes must be reflected in the documentation:

- Update the relevant arc42 chapter(s); what is built and what is planned is chapter 4.3, known limitations are chapter 11
- Create an ADR for an architectural decision, or add a dated *Update* section to the ADR whose reality changed ([format](../docs/README.md#architecture-decision-records))
- A new or changed setting goes into the [configuration reference](../docs/guides/configuration.md) and `deploy/.env.example`

See [docs/README.md](../docs/README.md) for the index.

## Docker

To test Docker changes locally:

```bash
cp deploy/.env.example deploy/.env       # set the token and the secret key
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
curl http://localhost:2909/health
docker compose -f deploy/docker-compose.yml down
```

Do not commit `deploy/.env`.

## Questions?

Open an issue or discuss in PR comments.

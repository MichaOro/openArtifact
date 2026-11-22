# Contributing to OpenArtifact

Thank you for your interest in OpenArtifact. This guide covers setup, the checks to run and the conventions to follow.

## Contribution process

1. **Fork and clone** the repository
2. **Create a branch** for your changes
3. **Implement** your feature or fix, with tests
4. **Run the local checks** below before committing
5. **Open a Pull Request** targeting `main`
6. **CI runs automatically** — all checks must pass
7. **Address review feedback**

## Setup

```bash
uv sync --all-extras                      # or: pip install -e ".[dev]"  (CI uses pip)
printf 'OPENARTIFACT_DATA_DIR=./.data\nOPENARTIFACT_HOST=127.0.0.1\n' > .env   # /data is not writable on a workstation; the host defaults to 0.0.0.0
uv run alembic upgrade head               # create the database
uv run openartifact                       # http://localhost:2909
```

Without `uv`, drop the `uv run` prefix inside your virtual environment. The browser tests need a browser once:
`playwright install chromium`. In open mode (no `OPENARTIFACT_API_TOKEN`) Code nodes are refused; for local development only,
set `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true` in `.env`. Never do that on a reachable host.

## Local Quality Checks

Run these from the repository root before opening a PR; CI runs the same:

```bash
ruff check .                  # 1. lint
ruff format --check .         # 2. formatting (ruff format . fixes it)
mypy .                        # 3. strict type checking
coverage run -m pytest -q && coverage report    # 4. unit and API tests under coverage (browser tests are excluded by default); fails below 95 % (fail_under in pyproject.toml)
pytest -m e2e                 # 5. browser tests (Playwright, needs `playwright install chromium`): slow, run before a push or PR
```

CI runs the unit tests once, under coverage, so a coverage failure also fails the test step; a change must not lower the gate. It additionally checks JavaScript syntax (`node --check`), Markdown links (`python tools/check_links.py`), the quarantine file and, in a built image, the container smoke test (`tools/smoke_container.sh`). All checks must pass, the browser tests included. Details, the browser-test fixtures and where tests live: [testing guide](../docs/guides/testing.md).
A change to the models needs an Alembic migration; `alembic check` (run by `tests/test_migrations.py`) fails on drift.

## Vocabulary

The product says **pipeline**, **stage**, **action** (made of execution nodes) and **artifact**. In the code and the API an
artifact is still a `task`, and pipelines and action definitions are stored as a **graph**. Never write **"workflow"**
in new code, UI text or documentation (ADR-015). User-facing text says "artifact", not "task".

Keep two words apart: a **run** is the current processing state of an artifact (`pipeline_runs`); an **execution** is the recorded
history of a run (`executions`, with its steps). The glossary ([arc42 chapter 12](../docs/architecture/arc42/12-glossary.md))
has the rest. Write "Code node", "HTTP node", "execution" and "credential store" in running text.

## Unused code: quarantine

Do not leave dead code behind and do not delete it blindly. Add an entry to `quarantine.json` (what, where, since when, a
regular expression `usage` that matches *calls*, not the definition; an optional `ignore` array of path globs for files
that must not count, such as tests). `tools/check_quarantine.py` (run by the `static` job of every CI run, and weekly; locally
`python tools/check_quarantine.py`) fails once an entry has had no calls for 14 days: then remove the code and the entry.
The file is empty today and should stay so: quarantine is a short waiting room, not a list of tolerated dead code. See ADR-014 §3.6 and [tools/README.md](../tools/README.md).

## Code and comments

- Type-annotated Python 3.12 (`mypy --strict`), `ruff` for lint and format (line length 100).
- Keep comments few and valuable: say why, not what.
- No secrets in code, tests or logs; configuration is `OPENARTIFACT_*` environment variables ([reference](../docs/guides/configuration.md)).
- No inline scripts in templates (the Content-Security-Policy is `script-src 'self'`); colours only as tokens in `tokens.css`.
- New node kinds and navigation entries: follow the [extending guide](../docs/guides/extending.md).

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/), one logical change per commit, imperative and lower case
after the colon:

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

## Documentation

Documentation is part of the change. Where it goes:

| Change | Update |
|--------|--------|
| New or changed setting | [configuration reference](../docs/guides/configuration.md) and `deploy/.env.example` |
| New or changed endpoint or MCP tool | OpenAPI description (summary, response model, error responses), [integration guide](../docs/guides/integration.md), [API reference](../docs/guides/api-reference.md), arc42 05.05 |
| New node kind or navigation entry | [extending guide](../docs/guides/extending.md), arc42 05.03 and the glossary |
| New migration or table | arc42 05.01 (domain model) and 05.03 |
| Security-relevant behaviour | [security guide](../docs/guides/security.md), arc42 08.01, and [SECURITY.md](../SECURITY.md) if the model changes |
| Built or planned feature, known limitation | arc42 chapter 4.3 (built and planned), chapter 11 (risks and technical debt) |
| Architectural decision | A new ADR, or a dated *Update* section on the ADR whose reality changed ([format](../docs/README.md#architecture-decision-records)), and arc42 chapter 9 |

Write for a senior engineer who does not know the project: plain, concrete, no marketing, and say what is *not* done. No
emojis. Do not point to private tracking systems; describe the intent in words. Relative links are checked in CI
(`tools/check_links.py`).

See [docs/README.md](../docs/README.md) for the map.

## Security

Do not report vulnerabilities in public issues; follow [SECURITY.md](../SECURITY.md). Code nodes run code with the application's
rights: treat every change near the executors, the access gate or the credential store as security-relevant and say so in
the pull request.

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

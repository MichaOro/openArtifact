# Contributing to OpenArtifact

Thank you for your interest in OpenArtifact! This guide covers the workflow for contributing code changes.

## Workflow

1. **Fork and clone** the repository
2. **Create a branch** for your changes
3. **Implement** your feature or fix
4. **Run local quality checks** before committing
5. **Open a Pull Request** targeting `main`
6. **CI runs automatically** — all checks must pass
7. **Address review feedback** if applicable

## Local Quality Checks

Before submitting a PR, run these locally:

```bash
cd apps/backend

# 1. Linting
ruff check .

# 2. Formatting
ruff format --check .

# 3. Type checking (strict)
mypy .

# 4. Tests
pytest -v

# 5. Coverage
coverage run -m pytest -q && coverage report
```

All checks must pass for CI to succeed.

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

- `main` — Stable development branch
- Feature branches — `<username>/<feature-name>` (e.g., `alice/user-auth`)
- PRs target `main`

## Architecture Documentation

Significant changes must be reflected in the architecture documentation:

- Update relevant arc42 chapter(s)
- Create/update ADR for architectural decisions
- Update roadmap table in README.md

See [docs/README.md](../docs/README.md) for documentation conventions.

## Docker

To test Docker changes locally:

```bash
docker build -t openartifact:local .
docker run -d --name test -p 2909:2909 -v openartifact-data:/data openartifact:local
curl http://localhost:2909/health
docker rm -f test
```

## Questions?

Open an issue or discuss in PR comments.

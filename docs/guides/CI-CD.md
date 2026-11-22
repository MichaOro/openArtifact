# CI/CD & Release Guide

This guide documents the automated CI/CD pipeline, Docker build process, and release procedure for OpenArtifact.

## Overview

```
Developer → PR → CI (lint → typecheck → test → browser tests → docker build) → main → Release (docker publish)
```

All checks run automatically. No manual intervention is required for development builds.

## CI Pipeline

### Triggers

| Event | Branch | Action |
|-------|--------|--------|
| PR to main | `main` | CI (lint, type check, tests, browser tests) and the PR image build |
| Push to main | `main` | CI + Docker build + smoke test |
| Version tag (`v0.1.0`, the `v` is required) | — | Release workflow |
| Weekly (Monday), pyproject changes | — | Dependency audit and quarantine check |

CI and the PR build run only when the change touches `apps/backend/**`, `Dockerfile`, `.dockerignore`,
`deploy/**`, `scripts/**`, `README.md` or `.github/workflows/**`.

### Stages

1. **Ruff lint** — `ruff check .`
2. **Ruff format** — `ruff format --check .`
3. **mypy** — `mypy .` (strict mode)
4. **pytest** — Unit and API tests, run once under coverage (browser tests excluded; `coverage.xml` is uploaded). See the [testing guide](testing.md)
5. **Browser tests** — `pytest -m e2e` (Playwright, headless Chromium, traces of failures are uploaded)
6. **Docker build and smoke test** — Image build, start, `/health`, `/` and `/api/info` (push to main only; the job has read-only permissions)

### Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI pipeline |
| `.github/workflows/release.yml` | Version-tagged release |
| `.github/workflows/pr-build.yml` | PR preview build (no push, no `packages` permission) |
| `.github/workflows/audit.yml` | `pip-audit` of the installed runtime dependencies; weekly, on dependency changes and by hand |
| `.github/dependabot.yml` | Weekly update pull requests for pip (`apps/backend`), the Dockerfile base image and GitHub Actions |
| `.github/workflows/quarantine.yml` | Weekly: fails when quarantined code (`quarantine.json`) has been unused for 14 days, as a reminder to remove it (`tools/check_quarantine.py`, ADR-014 §3.6) |

## Docker Build

### Image Naming

| Repository | URL |
|------------|-----|
| Primary | `ghcr.io/michaoro/openartifact` (the repository name, lower-cased by the workflow) |

### Tagging Scheme

| Trigger | Tags |
|---------|------|
| Version tag `v0.1.0` | `0.1.0`, `0.1.0.<run number>`, `sha-<full commit sha>`, `latest` (there is no `0.1` tag) |
| PR build | `pr-<number>` (not published) |
| Development builds | Not published |

### Build Process

1. **Stage 1 (builder):** `python:3.12-slim`, install dependencies from `pyproject.toml`
2. **Stage 2 (runtime):** `python:3.12-slim`, copy wheels + source, non-root user

### Image Labels

| Label | Value |
|-------|-------|
| `org.openartifact.commit` | Git commit SHA |
| `org.openartifact.version` | Semantic version |
| `org.openartifact.released` | Release tag |

## Release Procedure

### 1. Determine the Next Version

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR** — Incompatible API changes
- **MINOR** — New features (backward compatible)
- **PATCH** — Bug fixes

The version is written in one place, `apps/backend/openartifact/version.py`; the package build, `/health`,
`/api/info`, Swagger and the sidebar read it. Change that file in the release commit.

For OpenArtifact (pre-1.0), use `0.MINOR.PATCH` for breaking changes as MINOR.

### 2. Create a Release Tag

```bash
# Ensure main is up to date
git checkout main
git pull origin main

# Create and push a version tag
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

### 3. CI/CD Workflow Execution

The release workflow triggers automatically on tag push:

1. Starts on tags matching `v<major>.<minor>.<patch>` (no further validation: the tag is not compared with
   `apps/backend/openartifact/version.py`, so set the version there before tagging)
2. Builds the Docker image
3. Pushes to GHCR with appropriate tags
4. Creates a GitHub Release with auto-generated notes

### 4. Verify the Published Image

```bash
# Pull the image
docker pull ghcr.io/michaoro/openartifact:0.1.0

# Run it
docker run -d \
  --name openartifact \
  -p 2909:2909 \
  -v openartifact-data:/data \
  -e OPENARTIFACT_API_TOKEN="$(openssl rand -hex 32)" \
  -e OPENARTIFACT_SECRET_KEY="$(openssl rand -hex 32)" \
  ghcr.io/michaoro/openartifact:0.1.0

# Check health
curl http://localhost:2909/health

# The version is in the health answer (/api/info needs the token)
curl http://localhost:2909/health
```

### 5. Upgrade Instructions

Back up first ([operations guide](operations.md#backup)), then pull the new image. The compose file names
the image `ghcr.io/michaoro/openartifact:${OPENARTIFACT_TAG:-latest}`; set `OPENARTIFACT_TAG` in `deploy/.env` to
pin a version.

```bash
docker compose -f deploy/docker-compose.yml pull
docker compose -f deploy/docker-compose.yml up -d
```

The `/data` volume preserves all persistent data; migrations run when the container starts.

## Required Repository Settings

The following GitHub repository settings must be configured for CI/CD to work:

### Workflow Permissions

**Settings → Actions → General → Workflow permissions:**
- Set to **"Read and write permissions"** (required for GHCR publishing)

### Package Registry Access

**Settings → Packages:**
- Ensure `packages: write` is granted to Actions (configured in workflow YAML)

### Branch Protection (Recommended)

**Settings → Branches → Add rule for `main`:**
- Require pull request reviews (minimum 1)
- Require status checks to pass (CI)
- Require branches to be up to date before merging

## Troubleshooting

### CI Build Fails — Docker

- Ensure `.dockerignore` excludes `.venv/` and large directories
- Check that `Dockerfile` paths match the repository structure

### CI Fails — Python Tests

- Run locally: `cd apps/backend && ruff check . && ruff format --check . && mypy . && pytest`
- Check async test setup (pytest-asyncio)

### Docker Build Fails — Dependencies

- Verify `pyproject.toml` dependencies are resolvable
- Check that the Python version is 3.12 (`requires-python`)

### Release Fails — GHCR Permissions

- Verify "Read and write permissions" is set in Settings → Actions
- Ensure `GITHUB_TOKEN` has `packages: write` access
- Repository must have "Packages" permission enabled

### Smoke Test Fails

- Check container logs: `docker logs openartifact-smoke`
- Migration must succeed before the server starts
- Verify port 2909 is not already in use

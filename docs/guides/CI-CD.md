# CI/CD & Release Guide

This guide documents the automated CI/CD pipeline, Docker build process, and release procedure for OpenArtifact.

## Overview

```
Developer → PR → CI (lint → typecheck → test → docker build) → main → Release (docker publish)
```

All checks run automatically. No manual intervention is required for development builds.

## CI Pipeline

### Triggers

| Event | Branch | Action |
|-------|--------|--------|
| PR to main | `main` | Full CI (lint, typecheck, test, docker build) |
| Push to main | `main` | Full CI + Docker build + smoke test |
| Version tag (`v0.1.0`) | — | Release workflow |

### Stages

1. **Ruff lint** — `ruff check .`
2. **Ruff format** — `ruff format --check .`
3. **mypy** — `mypy .` (strict mode)
4. **pytest** — Full test suite with coverage
5. **Docker build** — Production image build (main only)

### Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI pipeline |
| `.github/workflows/release.yml` | Version-tagged release |
| `.github/workflows/pr-build.yml` | PR preview build |

## Docker Build

### Image Naming

| Repository | URL |
|------------|-----|
| Primary | `ghcr.io/michaoro/openartifact` |

### Tagging Scheme

| Trigger | Tags |
|---------|------|
| Version tag `v0.1.0` | `0.1.0`, `0.1`, `latest`, `sha-<commit>` |
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

1. Validates the version tag
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
  -e OPENARTIFACT_SECRET_KEY="$(openssl rand -hex 32)" \
  ghcr.io/michaoro/openartifact:0.1.0

# Check health
curl http://localhost:2909/health

# Verify version
curl http://localhost:2909/api/info
```

### 5. Upgrade Instructions

Users upgrade by pulling the new image:

```bash
docker compose -f deploy/docker-compose.yml pull
docker compose -f deploy/docker-compose.yml up -d
```

The `/data` volume preserves all persistent data.

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
- Check Python version matches `.python-version`

### Release Fails — GHCR Permissions

- Verify "Read and write permissions" is set in Settings → Actions
- Ensure `GITHUB_TOKEN` has `packages: write` access
- Repository must have "Packages" permission enabled

### Smoke Test Fails

- Check container logs: `docker logs openartifact-smoke`
- Migration must succeed before the server starts
- Verify port 2909 is not already in use

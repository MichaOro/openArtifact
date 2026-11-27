# CI/CD & Release Guide

This guide documents the automated CI/CD pipeline, Docker build process, and release procedure for OpenArtifact.

## Overview

```
Developer → PR → CI (static → lint → typecheck → test → browser tests) → main → docker smoke test
Maintainer → tag vX.Y.Z (equal to version.py) → Release (image on GHCR, GitHub Release)
```

All checks run automatically. No manual intervention is required for development builds.

## CI Pipeline

### Triggers

| Event | Branch | Action |
|-------|--------|--------|
| PR to main | `main` | CI (static checks, lint, type check, tests, browser tests) and the PR image build |
| Push to main | `main` | CI + Docker build + container smoke test |
| Version tag (`v0.1.0`, the `v` is required) | — | Release workflow |
| Weekly (Monday), changes to `pyproject.toml` or `uv.lock` | — | Dependency audit and quarantine check |

CI and the PR build are path-filtered: they run only when the change touches one of the paths listed at the
top of `.github/workflows/ci.yml` (the backend, the Dockerfile, `deploy/`, `scripts/`, `tools/`, the
documentation and the workflows themselves). A pull request that touches only other paths (for example
`LICENSE`) is not checked; if you add a new top-level directory with code or documentation, add it to the
filters of `ci.yml` and `pr-build.yml`.

### Stages

Every job that needs the Python dependencies installs them from `uv.lock` (`astral-sh/setup-uv` with the uv
release pinned in `ci.yml`, then `uv sync --frozen --all-extras`) and runs the tools with `uv run --no-sync`,
so CI, a local `uv sync` and the image use the same versions.

1. **static** — needs no Python dependencies: JavaScript syntax check of every file under `static/js`, the
   relative links of all Markdown files (`python tools/check_links.py`) and the quarantine file
   (`python tools/check_quarantine.py`; `quarantine.json` is empty at the moment, so any entry added to it
   starts the 14-day clock).
2. **lint** (job `lint`) — `uv lock --check` (fails when `pyproject.toml` changed without `uv lock`), then
   `ruff check .` and `ruff format --check .`
3. **type-check** — `mypy .` (strict mode)
4. **test** — `coverage run -m pytest`, run **once** under coverage, then `coverage report` (fails below
   `fail_under = 95`) and `coverage xml` (uploaded as an artifact). Browser tests excluded. See the
   [testing guide](testing.md).
5. **e2e** — `pytest -m e2e` (Playwright, headless Chromium, traces of failures are uploaded)
6. **docker** — builds the image and runs `tools/smoke_container.sh` against it (push to main only; the job
   has read-only permissions). The smoke test starts the image **as deployed**: read-only root file system,
   tmpfs `/tmp`, `--cap-drop ALL`, `no-new-privileges`, an API token and a secret key, as the compose file does.
   It first imports every module of the application in a throw-away container, then starts the container
   `openartifact-smoke-<pid>` on a random free port of `127.0.0.1` with a tmpfs `/data`, waits up to 30 seconds
   for `/health` to answer, and checks that `/api/tasks` answers `401` without a token, `200` with the bearer
   token and `401` with a wrong one. The container is removed when the script exits.

### Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI pipeline (jobs `static`, `lint`, `type-check`, `test`, `e2e`, `docker`) |
| `.github/workflows/release.yml` | Version-tagged release; refuses a tag that differs from `version.py` |
| `.github/workflows/pr-build.yml` | PR preview build (no push, no `packages` permission) |
| `.github/workflows/audit.yml` | `pip-audit` of the locked runtime dependencies (exported from `uv.lock`, as the image installs them); weekly, on dependency changes and by hand |
| `.github/dependabot.yml` | Weekly update pull requests for uv (`uv.lock` and `pyproject.toml` at the root), the Dockerfile base images (tag and digest) and GitHub Actions |
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

1. **Stage 1 (builder):** `python:3.12-slim` pinned by digest; `uv export --frozen` writes the runtime part of
   `uv.lock` with hashes, `pip install --require-hashes` installs exactly that, then the package itself (uv is
   mounted from the pinned `ghcr.io/astral-sh/uv` image for this step only)
2. **Stage 2 (runtime):** the same `python:3.12-slim` digest, copy the installed packages, non-root user; no uv

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

The version is written in one place, `openartifact/version.py`; the package build, `/health`,
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

1. Starts on tags matching `v<major>.<minor>.<patch>` and first checks that the tag (without the `v`) equals
   the version in `openartifact/version.py`; if not, the workflow fails before anything is
   built or published. Set the version there, commit it, then tag that commit.
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

# Check health (the answer carries the version; /api/info needs the token)
curl http://localhost:2909/health
```

This `docker run` is the shortest way to try an image. For anything that stays running use the compose file
(`deploy/docker-compose.yml`), which is the hardened reference: read-only root file system, tmpfs `/tmp`
(Execute Command nodes need a writable `/tmp`), `cap_drop: ALL`, `no-new-privileges`, process and memory limits. Do not
rebuild those flags by hand; see the [operations guide](operations.md).

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

### CI Fails — Static Checks

- Links: run `python tools/check_links.py` from the repository root; it names the file and the broken
  relative link or anchor.
- Quarantine: `python tools/check_quarantine.py` names the entry that is stale or overdue; remove the code
  and the entry (see [CONTRIBUTING](../../.github/CONTRIBUTING.md)).
- JavaScript: the job reports the file and line of the syntax error (`node --check <file>` reproduces it).

### CI Fails — Python Tests

- Run locally: `uv sync --all-extras`, then `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest` (from the repository root)
- `uv lock --check` fails: run `uv lock` and commit `uv.lock` with the `pyproject.toml` change
- Check async test setup (pytest-asyncio)

### Docker Build Fails — Dependencies

- The build installs `uv.lock` with `--frozen`: a stale lock is caught by `uv lock --check` in CI; run `uv lock`
- Check that the Python version is 3.12 (`requires-python`)

### Release Fails — GHCR Permissions

- Verify "Read and write permissions" is set in Settings → Actions
- Ensure `GITHUB_TOKEN` has `packages: write` access
- Repository must have "Packages" permission enabled

### Release Fails — Tag and Version Differ

- The workflow compares the tag with `openartifact/version.py`. Delete the tag
  (`git push --delete origin vX.Y.Z`, `git tag -d vX.Y.Z`), fix the version in a commit, tag again.

### Smoke Test Fails

- The script prints the last 40 lines of the container's log when a check fails; the container
  (`openartifact-smoke-<pid>`) is removed on exit, so `docker logs` afterwards finds nothing
- A module that fails to import (a missing runtime dependency) fails the first step
- Migration must succeed before the server starts
- The host port is chosen at random, so a port in use is not the cause
- The container runs read-only with a tmpfs `/tmp`: a change that writes elsewhere than `/data` and `/tmp` fails here first

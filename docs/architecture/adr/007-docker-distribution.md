# ADR-007: Docker Distribution and Deployment Model

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —

## 1. Title

Application Packaging and Docker Distribution Model

## 2. Context

OpenArtifact must be distributable as a self-hosted Docker-based installation package.

The user experience:

1. Install Docker and Docker Compose.
2. Download or obtain the deployment package.
3. Configure environment settings.
4. Start OpenArtifact via a documented command.
5. Access the application at `http://localhost:2909`.

The deployment must support reproducible builds, persistent data, external configuration, health checks, and graceful lifecycle management.

## 3. Decision Drivers

- Reproducible Docker image builds
- Persistent application data
- External configuration via environment variables
- Container health checks
- Restart behavior and reliability
- Database initialization and migrations
- Backup and recovery considerations
- Minimal operational complexity
- Single-command startup (`docker compose up`)

## 4. Considered Options

### Option A: Single Container (App + SQLite)

Single image containing the Python application and SQLite database in a persistent volume.

**Strengths:**
- Simplest possible deployment
- Single volume for data persistence
- Minimal Docker Compose configuration
- User experience: `docker compose up -d`

**Weaknesses:**
- App and DB in same container (violates separation of concerns if DB changes later)

### Option B: Multi-Container (App + PostgreSQL)

Dedicated containers for application and database.

**Strengths:**
- Clean separation of concerns
- Scalable independently

**Weaknesses:**
- Over-engineered for SQLite deployment
- More complex Docker Compose configuration
- More volumes and initialization scripts

### Option C: Single Container with Optional PostgreSQL

Default: single container with SQLite. Optional PostgreSQL via additional compose service.

**Strengths:**
- Best of both worlds
- SQLite as default (simplest path)
- PostgreSQL as optional override

**Weaknesses:**
- Two compose configurations to maintain
- Users must understand when to switch

## 5. Decision

**Option C (Single Container with Optional PostgreSQL)** is selected.

### Rationale

1. **SQLite defaults to single-container simplicity.** The default `docker-compose.yml` includes only the application container with a SQLite volume. This is the path of least resistance for the target user.

2. **PostgreSQL is optional for advanced deployments.** A `docker-compose.postgres.yml` override file provides the PostgreSQL service for users who need it.

3. **Configuration via environment variables.** All settings (port, host, database path, secrets) are controlled via `.env` file or environment variables.

4. **Reproducible builds via multi-stage Dockerfiles.** Python build environment is separate from the final runtime image.

### Recommended Dockerfile Structure

```
Dockerfile          — Multi-stage build (build + runtime)
docker-compose.yml  — Default (SQLite, port 2909)
docker-compose.postgres.yml — Optional PostgreSQL override
.env.example        — Environment variable documentation
scripts/docker-entrypoint.sh — Entry point with migration and health check
```

### Recommended Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `2909` | Application port |
| `DATABASE_PATH` | `/data/openartifact.db` | SQLite database location |
| `SECRET_KEY` | *(required)* | Application signing key |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Volume Mounts

- `/data` — Persistent application data (SQLite database, artifacts)
- No other volumes needed initially

## 6. Consequences

- **Easier:** Single-command deployment, local development, backups (file copy)
- **More difficult:** Multi-server deployments (deferred to WP-06)
- **Risks:** SQLite write contention under heavy load (mitigated by WAL mode)
- **Trade-off:** Slightly more maintainable docker-compose files vs. single config; justified by flexibility

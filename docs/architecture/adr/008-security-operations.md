# ADR-008: Security and Operations Foundation

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** [ADR-016](016-access-protection-integration-api-and-mcp.md), [ADR-017](017-request-hardening-and-signed-sessions.md)

## 1. Title

Security and Operations Foundation

## 2. Context

OpenArtifact requires foundational security and operational practices for:

- Configuration and secret handling
- Environment variable management
- Secure credential storage
- Logging without secret exposure
- Container security
- File system permissions
- Application health monitoring

Authentication and multi-tenancy are not required for the initial foundation.

## 3. Decision Drivers

- Secrets must never appear in logs
- Configuration must be externalized (env vars, not hardcoded)
- Container must run as non-root
- File system permissions must restrict access to persistent data
- Health checks must be available for Docker monitoring
- No security complexity without immediate need

## 4. Considered Options

### Option A: Built-in mechanisms

Use Python and Docker built-in capabilities (os.environ, file permissions, logging config).

**Strengths:**
- No external dependencies
- Simple to understand and audit
- Docker user namespace for non-root execution

**Weaknesses:**
- Limited secret rotation capability
- No secret scanning in logs

### Option B: External secret manager integration

Integrate with HashiCorp Vault or similar for secret management.

**Strengths:**
- Centralized secret management
- Secret rotation support
- Audit trail for secret access

**Weaknesses:**
- Operational overhead for single-user self-hosted deployment
- Over-engineered for current requirements
- Adds external dependency

## 5. Decision

**Option A (Built-in mechanisms)** is selected for the initial foundation, with secret manager integration deferred to WP-06.

### Rationale

1. **Single-user self-hosting has different threat model.** The user runs the container on their own infrastructure. Adding Vault would add complexity without proportional benefit at this stage.

2. **Environment variables are sufficient.** All secrets (API keys, secret keys) are passed via environment variables or `.env` files. No secrets are stored in the database or code.

3. **Logging configuration is critical.** A structured logging approach (Python `logging` module with JSON formatter) must be configured to explicitly exclude sensitive fields from log output.

4. **Container security is Docker-level.** Non-root user via Dockerfile `USER` directive, read-only filesystem where possible, minimal base image.

### Recommended Approach

- **Configuration:** Environment variables (`.env` file or Docker env)
- **Secrets:** Environment variables only; no secrets in code or database
- **Logging:** Python structured logging with explicit secret masking
- **Container:** Non-root user (UID 1000), minimal base image (Distroless or slim)
- **Health check:** `/health` endpoint returning HTTP 200 when application is ready
- **Restart policy:** `restart: unless-stopped` in docker-compose
- **File permissions:** 600 for database file, 750 for data directory
- **Secret manager:** Deferred — no external dependency now

## 6. Consequences

- **Easier:** Simple configuration, no external dependency for secrets
- **More difficult:** Secret rotation (deferred), multi-instance secret sharing (deferred)
- **Risks:** Secrets in `.env` file at rest (mitigated by file permissions on host)
- **Trade-off:** Simpler initial setup vs. enterprise-grade secret management; justified by self-hosted scope

## 7. Update (2026-11-22): what was added

The history above is kept. "Authentication ... not required for the initial foundation" and "JSON formatter" are
no longer accurate.

- **Access protection:** one API token for the whole application ([ADR-016](016-access-protection-integration-api-and-mcp.md)),
  with request hardening, signed expiring sessions and security headers ([ADR-017](017-request-hardening-and-signed-sessions.md)).
- **Logging:** one handler on the `openartifact` logger writing to stdout in one plain text format (there is no JSON
  format). A filter masks the configured token and secret key and any value after a secret-looking name
  (`password`, `token`, `api_key`, `authorization`, ...) in messages, arguments and tracebacks. See
  [arc42 8.3](../arc42/08-cross-cutting-concepts/08.03-logging-observability.md).
- **Container:** non-root user, read-only root file system, no capabilities, `no-new-privileges`, process and memory
  limits; `.dockerignore` is an allow-list.
- **Health check:** `GET /health` only, open without a token and under any `Host` header.
- **Secret manager:** still deferred. File permissions on the database file are not set by the application.

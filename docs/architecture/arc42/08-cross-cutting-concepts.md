# 8. Cross-cutting Concepts

## 8.1 Security Concepts

> TBD — Full security model and access control to be defined in WP-06 (Human Oversight and Review Mechanisms) and WP-07 (External Integrations).

**Foundational principles (ADR-008):**
- Secrets externalized via environment variables — no secrets in code or database
- Container security: non-root user, minimal base image
- Logging configuration must never expose secrets
- Authentication and multi-tenancy deferred to later Work Packages

## 8.2 Error Handling

> TBD — Detailed error handling strategies and conventions to be defined in WP-02.

**Foundational principles:**
- FastAPI exception handlers for structured HTTP error responses
- Consistent error format across all API endpoints
- User-friendly messages for frontend; detailed errors for logging
- Workflow execution errors must be persistently recorded and surfaced

## 8.3 Logging & Observability

> TBD — Comprehensive logging, monitoring, and tracing approach.

**Foundational principles (ADR-008):**
- Python structured logging (JSON formatter for production)
- Log levels configurable via `LOG_LEVEL` environment variable
- All sensitive values (tokens, keys, credentials) must be masked before logging
- Health check endpoint (`/health`) for Docker monitoring
- Database migrations via Alembic with version-controlled migration history

---

*This chapter follows the arc42 template. TBD fields are limited to concepts introduced in later Work Packages.*

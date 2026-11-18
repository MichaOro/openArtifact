# 8. Cross-cutting Concepts

## 8.1 Security Concepts

> TBD — Full security model and access control to be defined in WP-06 (Human Oversight and Review Mechanisms) and WP-07 (External Integrations).

**Implemented (WP-03):**
- Secrets externalized via environment variables — no secrets in code or database
- Container security: non-root user, minimal base image (ADR-008)
- Logging configuration masks sensitive fields (`secret_key`, `password`, `token`, `api_key`, etc.)
- Authentication and multi-tenancy deferred to later Work Packages

## 8.2 Error Handling

**Implemented (WP-03):**
- FastAPI exception handlers for `OpenArtifactError` (400), `ConfigurationError` (503), `DatabaseError` (503), and generic `Exception` (500)
- Production mode: stack traces suppressed from HTTP responses
- Development mode (`debug=true`): full stack traces in logs
- Consistent JSON error responses with `detail` field
- No secrets exposed in logs or HTTP responses

**Implemented (WP-04):**
- Database session auto-commit on success, auto-rollback on error
- Database connection errors logged at ERROR level, returned as 503

## 8.3 Logging & Observability

**Implemented (WP-03/04):**
- Python structured logging via `openartifact.logging_config.configure_logging()`
- Log levels configurable via `OPENARTIFACT_LOG_LEVEL` (default: `INFO`)
- Secret masking filter (`_SensitiveFilter`) on all log output
- Startup and shutdown events logged at INFO level
- Health check endpoint (`/health`) for Docker monitoring
- Database connection and WAL mode verified at startup
- Engine disposal logged at shutdown
- Error handling logs exceptions; suppressed in production HTTP responses

---

*This chapter follows the arc42 template. Cross-cutting concepts documented as WP-03/04 completed.*

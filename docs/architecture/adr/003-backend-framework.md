# ADR-003: Backend Framework

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** —

## 1. Title

Backend Framework Selection

## 2. Context

The backend framework must support:

- HTTP API for frontend and external integrations
- Long-running background processes (pipeline execution)
- Graceful shutdown and startup lifecycle
- Request/response validation
- Dependency injection / service composition
- Testing support
- WebSocket or Server-Sent Events for real-time progress (future)
- Docker-based self-hosted distribution on port 2909

## 3. Decision Drivers

- Async support for concurrent execution
- Automatic API documentation (OpenAPI/Swagger)
- Validation with Pydantic
- Dependency injection capabilities
- Background task management
- Extensibility (plugins, adapters)
- Testing with pytest ecosystem
- Community maturity and security

## 4. Considered Options

### Option A: FastAPI

**Strengths:**
- Automatic OpenAPI and Swagger UI generation
- Pydantic v2 validation
- Async-first design
- Dependency injection system
- Fast execution (Starlette-based)
- Excellent typing support
- Large and growing community
- AI-ecosystem-friendly

**Weaknesses:**
- Smaller ecosystem for advanced plugin architectures vs. Django
- Background task handling requires additional work (no built-in queue)

### Option B: Litestar (formerly Starlite)

**Strengths:**
- Built for complex applications
- Native plugin system
- Strong dependency injection
- GraphQL support
- OpenAPI and Swagger built-in

**Weaknesses:**
- Smaller community and ecosystem
- Less battle-tested in production
- Slower adoption curve for new developers

### Option C: Django / Django Ninja

**Strengths:**
- Batteries-included approach
- Admin interface, ORM, migrations built-in
- Mature and battle-tested

**Weaknesses:**
- Synchronous by default (async support exists but is incomplete)
- Heavier weight than needed for OpenArtifact's use case
- Less flexible plugin architecture
- Django's ORM vs. standalone persistence layer (OpenArtifact needs flexibility)

### Option D: Quart

**Strengths:**
- Flask-compatible async interface
- Familiar Flask patterns

**Weaknesses:**
- Smaller ecosystem
- Less built-in tooling
- No automatic API docs

## 5. Decision

**FastAPI** is selected as the backend framework.

### Rationale

1. **Async-first design aligns with OpenArtifact's concurrency model.** FastAPI's async/await foundation matches the platform's need for concurrent pipeline execution, background processing, and external process management.

2. **Pydantic validation is critical.** OpenArtifact's artifact model requires strong schema validation. Pydantic v2 provides high-performance, declarative validation — central to the platform's core abstraction.

3. **Automatic OpenAPI documentation.** Built-in Swagger and ReDoc reduce documentation overhead and provide immediate API discoverability.

4. **Extensibility pattern.** FastAPI's dependency injection and middleware system supports plugin/adapters architecture without forcing a rigid lifecycle.

5. **Testing support.** Integration with pytest, httpx, and factory_boy provides a mature testing ecosystem.

### Recommended Approach

- **FastAPI** as the HTTP framework
- **Pydantic v2** for validation and schema definitions
- **SQLModel** or **Alembic** for database migrations (deferred to WP-02)
- **Celery** or **arq** for background task queue (deferred to WP-03)

## 6. Consequences

- **Easier:** API documentation, validation, async execution, testing
- **More difficult:** Background task orchestration (deferred to WP-03), plugin architecture design
- **Risks:** FastAPI ecosystem growth (mitigated by Starlette's stability)
- **Trade-off:** No built-in admin interface or ORM — intentional, keeps framework minimal

## Update (2026-11-22)

`gunicorn` and `factory_boy` are no longer dependencies (the server is `uvicorn`, started through the `openartifact` command). There is no background task queue: runs are in-process
`asyncio` tasks ([ADR-013](013-execution-engine-and-runs.md)). The ORM is SQLAlchemy with Alembic.

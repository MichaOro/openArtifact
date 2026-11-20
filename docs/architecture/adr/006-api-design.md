# ADR-006: API Design

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —

> **Amendment (2026-11-20):** References to HTMX in this ADR are obsolete ([ADR-010](010-frontend-without-htmx.md)). The decision for a REST API with OpenAPI stands on its own merits. WebSocket/SSE streaming is **planned, not implemented**.

## 1. Title

API Design Approach for OpenArtifact

## 2. Context

OpenArtifact requires an API for:

- Frontend/backend communication (via HTMX/SSE/WebSocket or direct fetch)
- Future external integrations (webhooks, provider adapters)
- Structured workflow execution requests
- Provider adapters for AI agent execution
- Future REST API for third-party integrations

## 3. Decision Drivers

- Structured, typed request/response contracts
- Versioning strategy for future compatibility
- Support for synchronous and asynchronous operations
- Internal (frontend) and external (third-party) consumers
- Documentation and discoverability
- Authentication readiness (for future multi-user)

## 4. Considered Options

### Option A: REST API with OpenAPI

**Strengths:**
- Standard HTTP semantics (GET, POST, PUT, DELETE, PATCH)
- Automatic OpenAPI/Swagger documentation via FastAPI
- Versioning via URL path (`/api/v1/...`)
- Simple, well-understood by developers
- HTMX works naturally with REST patterns

**Weaknesses:**
- Not ideal for streaming/long-running operations
- Requires polling or SSE/WebSocket for real-time status

### Option B: GraphQL

**Strengths:**
- Flexible queries for complex data
- Single endpoint
- Type-safe via schema

**Weaknesses:**
- Over-engineered for OpenArtifact's initial scope
- Additional complexity (schema management, resolvers, caching)
- HTMX does not integrate naturally
- Larger learning curve for new developers

### Option C: gRPC

**Strengths:**
- Strongly typed protocol
- Efficient binary serialization
- Streaming support

**Weaknesses:**
- Overkill for a web application API
- No browser support without gRPC-Web
- HTMX integration impossible
- Not suitable for public-facing integrations

## 5. Decision

**REST API with OpenAPI** is selected as the primary API design, supplemented by WebSocket/SSE for real-time streaming.

### Rationale

1. **HTMX integrates naturally with REST.** HTMX is designed for standard HTTP requests and HTML responses. RESTful endpoints map cleanly to HTMX's `hx-get`, `hx-post`, and `hx-swap` patterns.

2. **OpenAPI/Swagger auto-generation.** FastAPI provides automatic OpenAPI schema generation and Swagger UI — critical for documenting the API for future integrations and provider adapters.

3. **Versioning strategy.** URL path versioning (`/api/v1/...`) provides backward compatibility and gradual migration capability.

4. **Real-time via WebSocket/SSE.** For workflow progress and event streaming, FastAPI's native WebSocket support and Server-Sent Events provide the needed real-time capability without complicating the REST API.

5. **Future extensibility.** The REST API serves both internal (HTMX frontend) and external (third-party integrations) consumers with the same foundation.

### Recommended Approach

- **Primary API:** REST with OpenAPI (FastAPI)
- **Versioning:** URL path (`/api/v1/...`)
- **Real-time:** WebSocket for workflow progress, SSE for event streaming
- **Documentation:** Automatic via FastAPI's OpenAPI generation
- **Internal communication:** HTMX + standard HTTP (no separate API layer for frontend)
- **External API:** `/api/v1/` endpoints with future JWT authentication

## 6. Consequences

- **Easier:** API documentation, HTMX integration, external integrations
- **More difficult:** Real-time status updates (mitigated by WebSocket/SSE), streaming large datasets
- **Risks:** REST polling overhead for real-time features (mitigated by SSE/WebSocket fallback)
- **Trade-off:** Simpler API design vs. GraphQL's flexibility; REST is sufficient for OpenArtifact's scope

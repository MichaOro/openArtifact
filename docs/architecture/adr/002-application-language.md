# ADR-002: Application Language

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —

## 1. Title

Application Language Selection for OpenArtifact

## 2. Context

OpenArtifact is an autonomous orchestration platform requiring:

- Long-running background processes (workflow execution)
- External process execution (agent runs)
- Concurrent workflow handling
- Integration with AI agents and model APIs
- Docker-based self-hosted distribution
- Maintainability across a growing codebase

The language must serve as the foundation for the application runtime, not just the API surface.

## 3. Decision Drivers

- Long-term maintainability
- Development productivity (including AI-assisted development)
- Runtime performance and memory efficiency
- Concurrent execution capabilities
- External process execution and lifecycle management
- Ecosystem for HTTP servers, async I/O, and background tasks
- Docker image size and build reproducibility
- Strong typing for complex domain logic
- Community maturity and security track record

## 4. Considered Options

### Option A: Python

**Strengths:**
- Excellent ecosystem for AI/ML integrations (OpenAI SDK, Anthropic SDK, LangChain, etc.)
- Strong async support (asyncio, FastAPI)
- High development productivity, very AI-agent-friendly
- Rich library ecosystem for HTTP, validation, serialization
- Mature concurrent execution (asyncio, threading, subprocess)
- Strong typing via type hints and mypy

**Weaknesses:**
- GIL limits true multi-threading (mitigated by asyncio and multiprocessing)
- Slightly larger Docker images (~150-200MB base)
- Startup latency for cold starts (less relevant for long-running server)
- Packaging and dependency resolution can be fragile across platforms

### Option B: TypeScript (Node.js / Bun / Deno)

**Strengths:**
- Single language for frontend and backend
- Excellent async/event-driven architecture
- Large npm ecosystem
- Fast development iteration
- Good Docker support

**Weaknesses:**
- Weaker typing compared to Python/Go (structural, not nominal)
- Suboptimal for CPU-bound tasks
- Background process management less mature than Python's asyncio/subprocess
- AI/ML integration ecosystem significantly smaller than Python's
- Module resolution complexity in monorepo setups
- Runtime performance variability across engines

### Option C: Go

**Strengths:**
- Excellent concurrency with goroutines
- Fast compilation and execution
- Small, reproducible Docker images (~10-20MB base)
- Strong typing
- Excellent for infrastructure tooling and CLI

**Weaknesses:**
- Weaker ecosystem for AI/ML integrations
- Manual error handling verbosity
- Less AI-agent-friendly codebase (no idiomatic dynamic typing patterns)
- Smaller standard library for HTTP validation and serialization
- Generics are limited compared to Rust or other modern languages

## 5. Decision

**Python** is selected as the application language.

### Rationale

1. **AI integration is a first-class concern.** OpenArtifact's core differentiator is orchestrating AI agents. Python's ecosystem is unmatched for this domain — all major AI providers provide first-class Python SDKs, and the async patterns align well with OpenArtifact's concurrent execution model.

2. **Concurrent execution model matches the platform.** asyncio + a modern async framework (FastAPI or Litestar) provides non-blocking HTTP handling, concurrent background task execution, and structured lifecycle management — all required by OpenArtifact.

3. **Development productivity and maintainability.** Python's type system (Python 3.12+ with PEP 695 type parameters) provides sufficient static guarantees for a complex domain model, while remaining readable and maintainable.

4. **Docker deployment is not a differentiator.** While Go produces smaller images, the ~150-200MB Python image is acceptable for a long-running server. Multi-stage builds and slim base images (Distroless, Alpine) can reduce this further.

5. **External process execution.** Python's `subprocess` module with asyncio integration provides robust process management for executing agent code.

### Recommended Stack

- **Language:** Python 3.12+
- **Backend Framework:** FastAPI (recommended) or Litestar
- **Task Queue:** asyncio + Celery (optional, deferred to WP-03)
- **Package Management:** uv (fast Python package manager)

## 6. Consequences

- **Easier:** AI integration, developer onboarding, async execution
- **More difficult:** True multi-threading (mitigated by architecture), cold start optimization
- **Risks:** GIL limitation for CPU-bound work (mitigated by async architecture and potential multiprocessing for heavy computation)
- **Trade-off:** Slightly larger Docker images vs. Go; justified by AI ecosystem advantages

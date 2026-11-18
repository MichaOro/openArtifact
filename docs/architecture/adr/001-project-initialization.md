# ADR-001: Project Initialization

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —

## 1. Title

Project Repository Initialization

## 2. Context

OpenArtifact requires a structured repository foundation to support:

- Maintainable application development
- Multiple AI coding agent environments
- arc42-based architecture documentation
- Architecture Decision Records (ADRs)
- Future Docker-based deployment
- Automated testing and CI

The repository was empty and needed an initial structure before any technical decisions (WP-01) can be made.

## 3. Decision Drivers

- Need for extensible and maintainable structure
- Support for multiple AI coding agents
- Standardized architecture documentation (arc42)
- Separation of concerns between application code, tests, docs, and deployment
- No premature technology decisions

## 4. Considered Options

### Option A: Monorepo with clear separation

Single repository with distinct top-level directories for apps, tests, docs, deploy, and tools.

### Option B: Multi-repo

Separate repositories for each component (backend, frontend, docs, deploy).

### Option C: Flat structure

Minimal structure with files organized by type.

## 5. Decision

**Option A (Monorepo)** was selected.

The repository uses a flat but clearly separated top-level structure:

```
apps/backend/    — Backend application source
apps/frontend/   — Frontend application source
tests/           — Automated tests
docs/            — Documentation (architecture, guides)
deploy/          — Deployment configurations
tools/           — Development tooling
scripts/         — Automation scripts
```

Technology choices for backend and frontend are deferred to WP-01.

## 6. Consequences

- **Easier:** Cross-component understanding, consistent tooling, unified CI
- **More difficult:** Repository size growth, need for clear directory boundaries
- **Risks:** Structure rigidity if not reviewed as the project grows
- **Trade-off:** More directories in root vs. component-level organization

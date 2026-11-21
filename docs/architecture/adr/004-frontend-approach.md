# ADR-004: Frontend Approach

> **Superseded.** The HTMX/Tailwind/Alpine stack described below was never implemented. See [ADR-010](010-frontend-without-htmx.md) for the current frontend decision. This document is kept for history.

**Status:** Superseded  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** [ADR-010](010-frontend-without-htmx.md)

## 1. Title

Frontend Application Approach

## 2. Context

OpenArtifact requires a web-based user interface for:

- Project and artifact management
- Pipeline orchestration and monitoring
- Human oversight (approvals, interventions)
- Configuration and settings
- Real-time progress updates

The frontend must be served by the same application instance (no separate public port) and support future extensibility.

## 3. Decision Drivers

- Integration with FastAPI backend
- Single-port delivery (port 2909)
- Build and deployment simplicity
- Component ecosystem for complex UIs
- Maintainability across developer team
- AI-agent-friendly development
- Progressive enhancement capability

## 4. Considered Options

### Option A: HTMX + Server-Side Templates (Jinja2)

**Strengths:**
- Zero build step required
- Serves directly through FastAPI
- Minimal JavaScript
- Server-driven architecture aligns with OpenArtifact's orchestration model
- Simple deployment
- Easy to maintain for core UI

**Weaknesses:**
- Limited interactivity for complex dashboards
- Less suited for real-time visualization
- Smaller component ecosystem
- May not scale well for highly interactive features

### Option B: React + Vite + SPA (served by FastAPI)

**Strengths:**
- Rich component ecosystem
- Real-time capabilities (WebSocket, SSE)
- Well-suited for complex dashboards and visualizations
- Large community and tooling
- Industry standard

**Weaknesses:**
- Build step required (added CI/CD complexity)
- Larger Docker image (Node.js build environment)
- Context switching between Python and TypeScript
- More files and configuration for simple features

### Option C: HTMX as primary, React for complex views

**Strengths:**
- Best of both worlds
- HTMX for standard CRUD and pipeline management
- React for interactive dashboards and real-time views

**Weaknesses:**
- Two UI frameworks to maintain
- Complexity in coordinating state between HTMX and React
- Potential inconsistency in UX

## 5. Decision

**HTMX + Jinja2** is selected as the primary frontend approach.

### Rationale

1. **Aligns with OpenArtifact's orchestration philosophy.** HTMX is server-driven: the server determines what the user sees, and HTML fragments are swapped into the page. This mirrors how OpenArtifact orchestrates pipelines — the server is the source of truth, and the UI is a view layer.

2. **No build step.** For a self-hosted application, eliminating the frontend build pipeline significantly reduces deployment complexity. The frontend is served directly by FastAPI (static file serving or Jinja2 templates).

3. **Single-port delivery.** Jinja2 templates and HTMX responses are served entirely through FastAPI on port 2909, with zero additional infrastructure.

4. **Pragmatic scope.** OpenArtifact's initial UI requirements (forms, tables, status displays, approvals) are well-suited to server-driven rendering. HTMX provides enough interactivity for these patterns.

5. **Extensibility path.** If complex interactive features are needed later, React can be added incrementally for specific views without removing HTMX.

### Recommended Approach

- **HTMX** for DOM manipulation and async requests
- **Jinja2** for server-side template rendering
- **Tailwind CSS** for styling (via CDN or minimal build)
- **Alpine.js** for lightweight client-side interactivity (dropdowns, toggles)
- **WebSocket** for real-time pipeline progress (via FastAPI WebSocket support)
- React can be added later for complex visualizations if needed

## 6. Consequences

- **Easier:** Deployment (no build step), server-side rendering, smaller Docker image
- **More difficult:** Complex real-time dashboards, client-side state management
- **Risks:** UI may feel less "app-like" for complex pipelines (mitigated by WebSocket progress streams)
- **Trade-off:** Less interactive UI vs. build complexity; HTMX is the right trade-off for OpenArtifact's scope

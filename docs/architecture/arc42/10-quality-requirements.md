# 10. Quality Requirements

## 10.1 Quality Scenarios

| Priority | Quality | Scenario |
|----------|---------|----------|
| Must | Deployability | A user can install OpenArtifact by copying `deploy/.env.example` to `deploy/.env`, running `docker compose -f deploy/docker-compose.yml up -d --build` and opening `http://localhost:2909` within 5 minutes. |
| Must | Self-hosting | The application runs entirely on the user's infrastructure without external service dependencies. |
| Must | Data persistence | Application data survives container restarts via Docker volume mounts. |
| Should | Concurrent execution | Multiple pipelines can execute concurrently without blocking the HTTP API. |
| Should | Reliability | The application recovers gracefully from crashes and restarts automatically. |
| Should | Extensibility | A new kind of node or navigation entry is one registered class plus tests (ADR-014); agent providers are planned. |
| Must | Security | With a token set, an unauthenticated request, a request with a foreign `Origin` or `Host`, or an oversized body never reaches a route (ADR-017). |
| Should | Real-time updates | A change on the board is visible in every open browser within a second (SSE; implemented). |
| Should | Usability | Every board action works by mouse, touch and keyboard; graph editor connections are pointer-only for now. |

## 10.2 Quality Tree

```
OpenArtifact Quality
├── Deployability (Must)
│   ├── Docker Compose one-command startup
│   ├── Build from the Dockerfile (the base image is a floating `python:3.12-slim` tag and the Python dependencies are not locked)
│   └── Single-port delivery (2909)
├── Reliability (Must)
│   ├── Graceful shutdown
│   ├── Health checks
│   └── Restart policies
├── Security (Must)
│   ├── One token, signed sessions
│   └── Request hardening, hardened container
├── Maintainability (Must)
│   ├── Type-safe Python
│   ├── Testable architecture
│   └── Clear module boundaries
├── Extensibility (Should)
│   ├── Registries for node kinds and navigation
│   └── Provider abstraction (planned)
├── Transparency (Should)
│   ├── created_by / started_by
│   └── Plain logging with secret masking
└── Real-time (Should)
    └── Server-Sent Events (implemented)
```


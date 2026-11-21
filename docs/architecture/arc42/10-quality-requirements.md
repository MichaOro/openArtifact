# 10. Quality Requirements

## 10.1 Quality Scenarios

| Priority | Quality | Scenario |
|----------|---------|----------|
| Must | Deployability | A user can install OpenArtifact by running `docker compose up -d` and accessing `http://localhost:2909` within 5 minutes. |
| Must | Self-hosting | The application runs entirely on the user's infrastructure without external service dependencies. |
| Must | Data persistence | Application data survives container restarts via Docker volume mounts. |
| Should | Concurrent execution | Multiple workflows can execute concurrently without blocking the HTTP API. |
| Should | Reliability | The application recovers gracefully from crashes and restarts automatically. |
| Should | Extensibility | New agent providers can be added without modifying the core application code. |
| Should | Real-time updates | A change on the board is visible in every open browser within a second (SSE; implemented). |
| Should | Usability | Every board action works by mouse, touch and keyboard. |

## 10.2 Quality Tree

```
OpenArtifact Quality
├── Deployability (Must)
│   ├── Docker Compose one-command startup
│   ├── Reproducible builds
│   └── Single-port delivery (2909)
├── Reliability (Must)
│   ├── Graceful shutdown
│   ├── Health checks
│   └── Restart policies
├── Maintainability (Must)
│   ├── Type-safe Python
│   ├── Testable architecture
│   └── Clear module boundaries
├── Extensibility (Should)
│   ├── Plugin/adapters architecture
│   └── Provider abstraction
├── Transparency (Should)
│   ├── Audit trail
│   └── Structured logging
└── Real-time (Should)
    └── Server-Sent Events (implemented)
```

---

*This chapter follows the arc42 template. TBD fields are limited to quality requirements introduced in later Work Packages.*

# 10. Quality Requirements

## 10.1 Quality Scenarios

Platform and usage qualities:

| Priority | Quality | Scenario |
|----------|---------|----------|
| Must | Deployability | A user can install OpenArtifact by copying `deploy/.env.example` to `deploy/.env`, running `docker compose -f deploy/docker-compose.yml up -d --build` and opening `http://localhost:2909` within 5 minutes. |
| Must | Self-hosting | The application runs on the user's infrastructure and needs no external service to work. Two documented exceptions: the Swagger UI page loads its assets from `cdn.jsdelivr.net`, and HTTP nodes call the addresses the user configures. |
| Must | Data persistence | Application data survives container restarts via Docker volume mounts. |
| Should | Concurrent execution | Multiple pipelines can execute concurrently (up to `OPENARTIFACT_MAX_CONCURRENT_RUNS`) without blocking the HTTP API. |
| Should | Reliability | The application recovers gracefully from crashes and restarts automatically; after a restart no run or execution stays `running`. |
| Should | Extensibility | A new kind of node or navigation entry is one registered class plus tests (ADR-014); agent providers are planned. |
| Must | Security | With a token set, an unauthenticated request, a request with a foreign `Origin` or `Host`, or an oversized body never reaches a route (ADR-017). |
| Should | Real-time updates | A change on the board is visible in every open browser within a second (SSE; implemented). |
| Should | Usability | Every board action works by mouse, touch and keyboard; graph editor connections are pointer-only for now (known limitation, [8.8](08-cross-cutting-concepts/08.08-accessibility-scope.md)). |

Scenarios for executing nodes, credentials and history (each is checked by tests; the file is named):

| Priority | Quality | Scenario | Checked by |
|----------|---------|----------|-----------|
| Must | Security | A stored credential appears in no API response, no event, no log line and no step result, even when the node prints it: not as it is, percent-encoded, Base64 or JSON-escaped. | `test_secrets.py`, `test_logging_config.py` |
| Must | Security | Without an API token and an own secret key of at least 32 characters, saving a credential (`PUT /api/secrets/{name}`) is refused with `409`, and in open mode an Execute Command node fails with an explanation unless `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN` is set. | `test_secrets.py`, `test_code_runner.py`, `test_config.py` |
| Must | Execution safety | An HTTP node whose host resolves to a cloud metadata address, or (by default) to a private or loopback address, sends nothing; a redirect is not followed. | `test_http_runner.py` |
| Must | Reliability | An Execute Command node that does not end is stopped after its `timeout_seconds` (at most 600) together with every process it started; a node over its CPU, memory, file or process limit fails with a reason instead of running unlimited; after a hard kill of the application the next start ends the orphans and removes their temp directories. | `test_code_runner.py`, `test_code_hardening.py` |
| Should | Traceability | Every start, restart included, creates an execution with its origin (`user`, `api` or `mcp`); after retention the newest execution of an artifact always remains; a policy change takes effect at once. | `test_history.py`, `test_engine.py` |
| Should | Maintainability | A new kind of execution node is a registered `NodeType` class, an executor and a view class; node settings live in the JSON `config`, so no column migration is needed. | `test_execution_nodes.py`, `test_graphs.py` |
| Should | Maintainability | The API and the web layer are imported only by themselves and the composition root (`app.py`), and the module-level imports of the package form no cycle, so a new import cannot break the start of the application unnoticed. | `test_import_structure.py` |
| Should | Performance | The global executions list pages with a keyset cursor: the cost of a page does not depend on how deep it is, and a page does not repeat or skip rows when executions are inserted or deleted meanwhile (index `ix_executions_started_at`). | `test_history_global.py` |
| Should | Observability | A running execution appears and updates in the History tab, on the `/executions` page and in the flow view within a second of the change (SSE `execution.updated`); a past execution can be shown as a flow without having recorded anything extra. | `test_history.py`, `test_execution_flow.py`, browser tests (`tests/e2e`) |

## 10.2 Quality Tree

```
OpenArtifact Quality
├── Deployability (Must)
│   ├── Docker Compose one-command startup
│   ├── Locked build from the Dockerfile (base images pinned by digest, runtime dependencies from `uv.lock` with hashes; the build backend of the package itself is not pinned)
│   └── Single-port delivery (2909)
├── Reliability (Must)
│   ├── Graceful shutdown, restart recovery (runs, executions, orphan code processes)
│   ├── Health checks, restart policies
│   └── Bounded execution: run cap, timeouts, step limit
├── Security (Must)
│   ├── One token, signed sessions
│   ├── Request hardening, hardened container
│   └── Credentials encrypted at rest, masked everywhere
├── Safety of execution (Must)
│   ├── Execute Command nodes: limits, process group, token required, off switch (no sandbox)
│   ├── HTTP nodes: address checks, no redirects, size and time bounds
│   └── Fail closed: a limit that cannot be applied fails the node
├── Maintainability (Must)
│   ├── Type-safe Python
│   ├── Testable architecture, coverage gate of 95 %
│   └── Clear module boundaries, one source per fact
├── Extensibility (Should)
│   ├── Registries for node kinds, executors and navigation
│   └── Provider abstraction (planned)
├── Observability (Should)
│   ├── Execution history, flow replay, retention
│   ├── created_by / started_by
│   └── Plain logging with secret masking; no metrics or traces yet
├── Performance (Should)
│   └── Keyset paging, indexes on the executions table
├── Usability (Should)
│   └── Board by pointer, touch and keyboard; editor connections by pointer only
└── Real-time (Should)
    └── Server-Sent Events (implemented)
```

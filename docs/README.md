# Documentation

Index of everything under `docs/`. The product is described in the [repository README](../README.md).

## Where to start

| You are | Read first |
|---------|-----------|
| New to the project | [Repository README](../README.md), then [Concepts](guides/concepts.md) |
| Operating it | [Security for operators](guides/security.md), [Operate the Docker deployment](guides/operations.md), [Configuration reference](guides/configuration.md) |
| Using the API or MCP | [Sign in and use the API and MCP](guides/integration.md), [API reference](guides/api-reference.md), [Credentials](guides/credentials.md) |
| Developing | [CONTRIBUTING](../.github/CONTRIBUTING.md), [Extending the application](guides/extending.md), [Testing](guides/testing.md), [Development](guides/development.md) |
| Reviewing the architecture | [arc42 chapter 4](architecture/arc42/04-solution-strategy.md) (built and planned), [chapter 5](architecture/arc42/05-building-block-view/README.md), [chapter 8](architecture/arc42/08-cross-cutting-concepts/README.md), [chapter 11](architecture/arc42/11-risks-and-technical-debt.md), the [ADRs](architecture/adr/) |

To report a vulnerability: [SECURITY.md](../SECURITY.md).

## Guides

How to run, use, change and test the application.

| Guide | For |
|-------|-----|
| [Concepts](guides/concepts.md) | Artifact, pipeline, stage, action, execution node, run, execution, flow: how they fit together |
| [Security for operators](guides/security.md) | Checklist, the security model and its limits (token, secret key, Code nodes, HTTP nodes) |
| [Configuration reference](guides/configuration.md) | Every `OPENARTIFACT_*` setting, the compose-only variables, `FORWARDED_ALLOW_IPS` |
| [Sign in and use the API and MCP](guides/integration.md) | Token, browser sign-in, `curl` against `/api/v1`, MCP client setup |
| [API reference](guides/api-reference.md) | The operations of the browser and integration APIs and the MCP tools, generated from the OpenAPI schema |
| [The UI catalog](guides/ui-catalog.md) | The one definition of buttons and the other components, the tokens for light and dark, contrast rules, how to extend it |
| [Execution nodes](guides/execution-nodes.md) | Timer, Code, HTTP and Output nodes: settings, limits, what is and is not isolated |
| [Agents and LLM providers](guides/agents.md) | Providers and models, agents with drafts and versions, the Agent node, what an execution keeps, limits |
| [Credentials](guides/credentials.md) | The credential store: API, references from nodes, limits, backup |
| [Execution history](guides/execution-history.md) | Recording, retention, the flow view, the global executions page, the API |
| [Operate the Docker deployment](guides/operations.md) | Start, update, health, backup and restore of the SQLite volume |
| [Run behind a reverse proxy](guides/reverse-proxy.md) | nginx and Caddy, TLS, `Host`, forwarded headers, cookie, limits |
| [Languages (i18n)](guides/i18n.md) | Switching the language, adding one, what is not translated |
| [Extending the application](guides/extending.md) | A new node kind, a new navigation entry |
| [Testing](guides/testing.md) | Unit and browser tests, coverage, quality checks |
| [CI/CD and releases](guides/CI-CD.md) | Pipelines, image name and tags, release procedure |

## Architecture

```
docs/architecture/
├── arc42/    — the arc42 documentation, 12 chapters
└── adr/      — Architecture Decision Records (numbered; the list is in chapter 9)
```

The diagrams are inline in the chapters (text diagrams); there is no separate diagram folder.

### arc42 chapters

The documentation follows the [arc42 template](https://docs.arc42.org/). The chapters describe the code as it is; where
something is planned, it says so. If you find a statement that is no longer true, that is a bug: fix it or open an issue.

| # | Chapter | File |
|---|---------|------|
| 1 | Introduction and Goals | [01-introduction-and-goals.md](architecture/arc42/01-introduction-and-goals.md) |
| 2 | Architecture Constraints | [02-architecture-constraints.md](architecture/arc42/02-architecture-constraints.md) |
| 3 | Context and Scope | [03-context-and-scope.md](architecture/arc42/03-context-and-scope.md) |
| 4 | Solution Strategy (including what is built and what is planned) | [04-solution-strategy.md](architecture/arc42/04-solution-strategy.md) |
| 5 | Building Block View | [05-building-block-view/](architecture/arc42/05-building-block-view/README.md) |
| 6 | Runtime View | [06-runtime-view/](architecture/arc42/06-runtime-view/README.md) |
| 7 | Deployment View | [07-deployment-view.md](architecture/arc42/07-deployment-view.md) |
| 8 | Cross-cutting Concepts (security, errors, logging, board) | [08-cross-cutting-concepts/](architecture/arc42/08-cross-cutting-concepts/README.md) |
| 9 | Architecture Decisions (index of the ADRs) | [09-architecture-decisions.md](architecture/arc42/09-architecture-decisions.md) |
| 10 | Quality Requirements | [10-quality-requirements.md](architecture/arc42/10-quality-requirements.md) |
| 11 | Risks and Technical Debt (known limitations) | [11-risks-and-technical-debt.md](architecture/arc42/11-risks-and-technical-debt.md) |
| 12 | Glossary | [12-glossary.md](architecture/arc42/12-glossary.md) |

Chapters that grow are split into a folder with the same number (`05-building-block-view/`): a `README.md` as index and
numbered files per topic (`05.01-…`, zero-padded so they sort). Small chapters stay a single file; split a chapter once it
exceeds roughly 300 lines or three independent topics.

### Architecture Decision Records

ADRs are in [`architecture/adr/`](architecture/adr/); the index with status and relations is
[arc42 chapter 9](architecture/arc42/09-architecture-decisions.md). Each follows [`TEMPLATE.md`](architecture/adr/TEMPLATE.md).

- **Name:** `adr/NNN-short-kebab-title.md`, numbered in sequence (for example `017-request-hardening-and-signed-sessions.md`).
- **Header:** Status, Date, Supersedes, Superseded by, Amends, Amended by. Keep both sides of a relation in step.
- **Status:** *Proposed*, *Accepted*, *Superseded* (replaced entirely by a newer ADR) or *Deprecated* (no longer relevant, nothing replaces it).
- **History is kept.** When reality changes, add a dated `Update (YYYY-MM-DD)` section at the end and the relation lines; correct
  the body only for a plain error (a wrong path or name).
- **Creating one:** copy the template to the next number, fill every section, add it to chapter 9, and link it from the
  chapter it affects.

## Keeping it true

Architecture documentation evolves with the system:

- Component changes: update the building block view (chapter 5); runtime behaviour: chapter 6; deployment: chapter 7 and the guides.
- A decision: a new ADR or a dated update, and chapter 9.
- A new risk or a known limitation: chapter 11. New terms: chapter 12.
- The table of what to update for which change is in [CONTRIBUTING](../.github/CONTRIBUTING.md#documentation).
- A new or changed setting: [configuration reference](guides/configuration.md) and `deploy/.env.example`.
- Vocabulary: the UI says *artifact*, the code says `task`; *pipeline*, *stage*, *action*; never "workflow" (ADR-015).

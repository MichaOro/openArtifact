# Documentation

Index of everything under `docs/`. The product is described in the [repository README](../README.md).

## Guides

How to run, use, change and test the application.

| Guide | For |
|-------|-----|
| [Configuration reference](guides/configuration.md) | Every `OPENARTIFACT_*` setting, the compose-only variables, `FORWARDED_ALLOW_IPS` |
| [Sign in and use the API and MCP](guides/integration.md) | Token, browser sign-in, `curl` against `/api/v1`, MCP client setup |
| [Operate the Docker deployment](guides/operations.md) | Start, update, health, backup and restore of the SQLite volume |
| [Run behind a reverse proxy](guides/reverse-proxy.md) | nginx and Caddy, TLS, `Host`, forwarded headers, cookie, limits |
| [Extending the application](guides/extending.md) | A new node kind, a new navigation entry |
| [Testing](guides/testing.md) | Unit and browser tests, coverage, quality checks |
| [CI/CD and releases](guides/CI-CD.md) | Workflows, image name and tags, release procedure |

For contributors: [CONTRIBUTING](../.github/CONTRIBUTING.md).

## Architecture

```
docs/architecture/
├── arc42/    — the arc42 documentation, 12 chapters
└── adr/      — Architecture Decision Records (001 to 020)
```

The diagrams are inline in the chapters (text diagrams); there is no separate diagram folder.

### arc42 chapters

The documentation follows the [arc42 template](https://docs.arc42.org/). The chapters describe the code as it is; where
something is planned, it says so.

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

## Research material

[`BESTANDSAUFNAHME.md`](../BESTANDSAUFNAHME.md) and [`bestandsaufnahme/`](../bestandsaufnahme/) (German, at the repository
root) are an inventory of the AI pipeline that preceded this product. They are input for the pipeline editor's design, not a
description of OpenArtifact, and contain machine-local paths of their author.

## Keeping it true

Architecture documentation evolves with the system:

- Component changes: update the building block view (chapter 5); runtime behaviour: chapter 6; deployment: chapter 7 and the guides.
- A decision: a new ADR or a dated update, and chapter 9.
- A new risk or a known limitation: chapter 11. New terms: chapter 12.
- A new or changed setting: [configuration reference](guides/configuration.md) and `deploy/.env.example`.
- Vocabulary: the UI says *artifact*, the code says `task`; *pipeline*, *stage*, *action*; never "workflow" (ADR-015).

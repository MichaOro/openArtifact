# Architecture Documentation

This directory contains the architecture documentation for OpenArtifact.

## Structure

```
docs/architecture/
├── arc42/           — Complete arc42 documentation (12 chapters)
├── adr/             — Architecture Decision Records
└── diagrams/        — Architecture diagrams
```

## arc42 Chapters

The architecture documentation follows the [arc42 template](https://docs.arc42.org/).

| # | Chapter | File | Status |
|---|---------|------|--------|
| 1 | Introduction and Goals | [01-introduction-and-goals.md](arc42/01-introduction-and-goals.md) | TBD |
| 2 | Architecture Constraints | [02-architecture-constraints.md](arc42/02-architecture-constraints.md) | TBD |
| 3 | Context and Scope | [03-context-and-scope.md](arc42/03-context-and-scope.md) | TBD |
| 4 | Solution Strategy | [04-solution-strategy.md](arc42/04-solution-strategy.md) | TBD |
| 5 | Building Block View | [05-building-block-view.md](arc42/05-building-block-view.md) | TBD |
| 6 | Runtime View | [06-runtime-view.md](arc42/06-runtime-view.md) | TBD |
| 7 | Deployment View | [07-deployment-view.md](arc42/07-deployment-view.md) | TBD |
| 8 | Cross-cutting Concepts | [08-cross-cutting-concepts.md](arc42/08-cross-cutting-concepts.md) | TBD |
| 9 | Architecture Decisions | [09-architecture-decisions.md](arc42/09-architecture-decisions.md) | See ADRs |
| 10 | Quality Requirements | [10-quality-requirements.md](arc42/10-quality-requirements.md) | TBD |
| 11 | Risks and Technical Debt | [11-risks-and-technical-debt.md](arc42/11-risks-and-technical-debt.md) | TBD |
| 12 | Glossary | [12-glossary.md](arc42/12-glossary.md) | TBD |

## Architecture Decision Records (ADRs)

ADRs are stored in the [`adr/`](adr/) directory. Each ADR is a numbered Markdown file following the template in [`adr/TEMPLATE.md`](adr/TEMPLATE.md).

### Naming Convention

```
adr/YYYY-MM-DD-<short-description>.md
```

Examples:

- `adr/001-project-initialization.md`
- `adr/002-technology-stack.md`

### Status Values

- **Proposed** — Under discussion
- **Accepted** — Agreed upon
- **Deprecated** — Superseded by a later decision
- **Superseded** — Replaced by a newer ADR

### Creation Process

1. Copy `adr/TEMPLATE.md` to `adr/YYYY-MM-DD-<description>.md`
2. Increment the number sequentially
3. Fill in all sections
4. Reference the ADR from arc42 chapter 9
5. Submit for review

## Diagrams

Architecture diagrams are stored in [`diagrams/`](diagrams/).

Preferred formats:

- **Text-based diagrams** (Mermaid, ASCII) — maintainable, version-control friendly
- **SVG** — for published diagrams
- **PlantUML source** — for diagrams that need to be regenerated

## Maintenance

Architecture documentation must evolve alongside the system:

- **Component changes** → Update building block view (chapter 5)
- **Runtime behavior changes** → Update runtime view (chapter 6)
- **Deployment changes** → Update deployment view (chapter 7)
- **Architectural decisions** → Create or update ADRs; update chapter 9
- **New risks** → Update risks section (chapter 11)
- **Glossary updates** → Maintain glossary (chapter 12)

Documentation updates are expected as part of any significant technical work.

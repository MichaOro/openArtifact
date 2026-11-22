# ADR-005: Database and Persistence

**Status:** Accepted  
**Date:** 2026-11-18  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** [ADR-020](020-sqlite-stays-postgres-as-data-source.md)

## 1. Title

Database Selection and Persistence Strategy

## 2. Context

OpenArtifact requires a relational database for:

- Project, artifact, and pipeline state persistence
- Execution history and audit trails
- Configuration storage
- Future multi-user data (user accounts, permissions)

The database must support self-hosted single-container deployment while allowing future scalability.

## 3. Decision Drivers

- Single-instance self-hosting (SQLite first)
- Concurrent access for pipeline execution
- Transaction handling and data integrity
- Migration support
- Backup and recovery
- Docker volume management simplicity
- Future scalability path
- Zero external dependencies for local development

## 4. Considered Options

### Option A: SQLite

**Strengths:**
- Zero configuration — single file
- Ideal for single-instance self-hosting
- ACID-compliant with WAL mode for concurrent reads
- Small Docker image footprint
- Fast for read-heavy workloads
- Built-in backup (file copy in WAL mode)
- Same engine as PostgreSQL (SQL dialect compatibility via careful use)

**Weaknesses:**
- Write contention under heavy concurrency (mitigated by WAL)
- No native network access (must connect locally)
- No built-in user/permission management (not needed initially)
- Limited scalability beyond single-server

### Option B: PostgreSQL

**Strengths:**
- Mature, battle-tested at scale
- Full concurrency support
- Advanced features (JSONB, full-text search, extensions)
- Native network access
- Built-in replication and backup tooling

**Weaknesses:**
- Additional container and configuration overhead
- More complex Docker setup (env vars, volumes, initialization scripts)
- Heavier resource requirements
- Overkill for single-instance self-hosting at early stages

## 5. Decision

**SQLite** is selected as the initial database, with PostgreSQL as an upgrade path.

### Rationale

1. **Self-hosting is the primary distribution model.** For users running OpenArtifact via `docker compose up`, a single SQLite file is dramatically simpler than configuring PostgreSQL. One volume mount, no initialization scripts, no connection pooling configuration.

2. **SQLite WAL mode supports concurrent access.** OpenArtifact's primary concurrency pattern is pipeline execution (background tasks). SQLite's WAL mode allows concurrent reads and serializes writes — sufficient for the initial scope.

3. **SQL dialect compatibility.** By avoiding PostgreSQL-specific features (CTEs with window functions, advanced JSONB) and using a SQL dialect-agnostic ORM, the migration path to PostgreSQL is straightforward if needed.

4. **No justified need for PostgreSQL yet.** The requirements for concurrent writes, data volume, and multi-user access at early stages do not justify the operational complexity of PostgreSQL.

5. **Upgrade path is known.** If SQLite becomes a bottleneck, migration to PostgreSQL is a configuration change (connection string) with potential schema adjustments.

### Recommended Approach

- **Primary database:** SQLite (WAL mode)
- **ORM/Migration layer:** SQLModel or SQLAlchemy + Alembic
- **Migration strategy:** Alembic migrations for schema evolution
- **Backup:** Documented file-copy procedure for SQLite WAL mode
- **Upgrade path:** Connection string change to PostgreSQL, schema migration via Alembic

## 6. Consequences

- **Easier:** Single-container deployment, local development, backup (file copy)
- **More difficult:** Scaling beyond single-server (deferred to WP-06)
- **Risks:** Write contention under heavy concurrent pipeline execution (mitigated by WAL mode and async execution serialization)
- **Trade-off:** Simpler deployment vs. future scalability; SQLite is the right starting point

## Update (2026-11-22): SQLite stays, PostgreSQL is not an upgrade path

The history above is kept. Two statements in it no longer hold and are corrected by
[ADR-020](020-sqlite-stays-postgres-as-data-source.md):

- "Same engine as PostgreSQL" and "a configuration change (connection string)" were never true. `database_url`
  is built as `sqlite+aiosqlite` from the data directory and file name, the engine is created with SQLite-only
  connection arguments and the WAL and foreign-key pragmas are set per connection, and several migrations use
  SQLite's batch mode. Moving to PostgreSQL would need code changes, and it is **not planned**.
- openArtifact's own data stays in SQLite (one file in one container). PostgreSQL may come later as a *data
  source* that pipelines read through a connector layer, not as the application's database.
- "Built-in backup (file copy)" is only safe with SQLite's backup API in WAL mode; see the
  [operations guide](../../guides/operations.md#backup).
- The ORM is SQLAlchemy with Alembic (not SQLModel).

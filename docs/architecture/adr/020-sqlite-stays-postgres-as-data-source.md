# ADR-020: SQLite stays; PostgreSQL only as a data source

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-005](005-database-persistence.md), [ADR-007](007-docker-distribution.md), [ADR-009](009-technology-summary.md)  
**Amended by:** —

## 1. Title

OpenArtifact's own data stays in SQLite for good; PostgreSQL is not an upgrade path of the application.

## 2. Context

ADR-005, ADR-007 and ADR-009 chose SQLite "with PostgreSQL as an upgrade path" and described an optional
`docker-compose.postgres.yml`. That path was never built, and the claim that it is "a configuration change" was
wrong: the engine is SQLite-only (URL, connection arguments, pragmas), and the migrations rely on SQLite's batch mode.
Meanwhile the product direction is clear: one self-hosted container for one team, in-process execution
(ADR-013), a single volume to back up.

## 3. Decision

- **SQLite is the application's database, permanently.** One file in one volume in one container. There is no
  PostgreSQL override, no `DATABASE_URL` setting, and no plan to build one.
- **PostgreSQL will only come later as a data source** that pipelines and actions read through a connector layer
  (board card "OPT 11"), the same way other external systems would be connected. It is not designed yet.
- The consequences of "one process, one volume" are accepted and documented (arc42 chapter 11): the event bus, the
  run engine and the run cap live in process memory; do not run several containers on one volume.
- Backup is SQLite's backup API and a written restore procedure ([operations guide](../../guides/operations.md)).

## 4. Consequences

- **Easier:** one operational story, no connection pool tuning, no second container, simple restore.
- **More difficult:** no horizontal scaling and no managed-database operations; heavy write contention is the
  limit (SQLite WAL serialises writers, each write is short).
- **Documentation:** ADR-005, ADR-007 and ADR-009 carry dated Update sections; the older sentences about an upgrade path
  stay as history and are withdrawn there. The constraints chapter (arc42 2.1) states SQLite without an upgrade path.

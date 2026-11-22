# ADR-022: Node settings as JSON config

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-014](014-building-blocks-and-extension-points.md) (update of 2026-11-22), [ADR-019](019-module-boundaries-and-single-sources.md) §3.1  
**Amended by:** —  
**Implemented in:** migration 0021 (`graph_nodes.config`, JSON, default `{}`); `graph/node_types.py` (`Setting`), `graph/repository.py`, `static/js/editor/setting-controls.js`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md); guide [extending](../../guides/extending.md)

## 1. Title

Where the settings of a node are stored and how they are described.

## 2. Context

Until ADR-014 a setting was a column of `graph_nodes` plus a field of the update schema. The timer needed one
number and one switch; Code and HTTP nodes need many settings, some of them long (source code, headers, a body).
A column per setting would mean a migration for every new kind.

## 3. Decision

- All settings added since live in `graph_nodes.config`, one JSON object per node. `seconds` and `fail_enabled`
  stay columns.
- A `Setting` (`graph/node_types.py`) describes one value: `key`, `label`, `type` (`integer`, `switch`, `text`,
  `lines`, `code`, `select`), bounds (`minimum`, `maximum`, `max_length`), `options`, `default`, `stored_in`
  (`column` or `config`) and an optional check rule (not sent to the editor). The registry of node types holds the
  settings; the repository derives the accepted keys from it and validates every value in Python.
- The editor draws its controls from `GET /api/node-types` (`setting-controls.js`); it contains no list of
  settings of its own.

## 4. Consequences

- A new kind needs no column migration. Only the kind constraint of `graph_nodes` changes when a kind is added
  (migration 0021 added `code` and `http`).
- Validation lives in one place; the editor follows the description.
- There is no SQL over settings, and the shape of `config` exists only in the code, not in the database schema.

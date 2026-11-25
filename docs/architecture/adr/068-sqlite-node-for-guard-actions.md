# ADR-068: The SQLite node: read-only data of the application, for guard actions

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-041](041-github-and-postgres-nodes.md) (a node that runs SQL), [ADR-060](060-guards.md) (what a guard action can read)  
**Implemented in:** `engine/sqlite_runner.py`, `engine/guard_views.py`, `graph/nodes/sqlite.yaml`, `graph/nodes/sqlite_tool.yaml`, `agents/local_tools.py` (`build_sqlite_tool`), `tests/test_sqlite_node.py`  
**Affected chapters:** guides [execution-nodes](../../guides/execution-nodes.md), [guards](../../guides/guards.md), [extending](../../guides/extending.md)

## 1. Context

A guard that judges whether a run is healthy has to look at data of the application: how long ago the last step was, which tool
calls an agent made, how many artifacts a lane holds. The owner's n8n guards did exactly that (an AI agent reading a database the
guard was given). For the other nodes, the information is in the database of the application, which also holds secrets (credentials,
tokens, provider keys, settings) and the content of every run. A node that runs SQL on it must therefore be safe by construction.
It is for every user, not only for developers; it is never for writing (for that there are the API, MCP and the interface).

## 2. Decision

- **A node "SQLite"** (flow node, menu group *Apps and data* like Postgres) and **a tool "SQLite Tool"** (for an agent, like the Postgres
  Tool) run **one read-only statement**. Both are **guard-only** (`purposes: [guard]`, ADR-067): the "+" menu of a pipeline action does
  not offer them and the server refuses them there.
- **The database enforces it, not the text of the statement.** The file is opened read-only (`mode=ro`, `query_only`). An
  **authorizer** (`sqlite3.set_authorizer`) decides every step the engine takes while it prepares the statement: a `SELECT` is fine;
  `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `ATTACH`, `PRAGMA`, transactions, `VACUUM`, ... are refused; so are
  `load_extension`, `fts3_tokenizer` and the like as functions. One statement only; values travel as parameters (`?1`, `?2`); a time
  limit interrupts the engine (also a recursive query that never ends); a row limit and a byte limit cut the answer.
- **Only views are read.** A data source lists the views a statement may read (for the application's own database the five
  `v_guard_*` views, see `engine/guard_views.py`: runs, steps, tool calls, artifacts, lanes, without content columns or secrets).
  Naming a table, quoted or in another case, is refused. What a view reads inside is learnt from its definition in the very
  database (`view_reads`), so a `WITH` that is named like a listed view cannot read more than that view does. The views are made again
  at every start (`guard_views.install`), so they follow the tables.
- **A fixed floor no setting lifts:** tables whose name says secret, credential, token, provider, setting or password, and
  columns that hold a password, a key or a hash, can never be read, not even through a view. The author can block **more** (the
  setting *Blocked tables*, `table` or `table.column`, an optional setting), never fewer; a view that reads a blocked column is
  blocked as a whole. A count (`count(*)`, `EXISTS`) of a table that is not denied shows how many rows there are, never what is in
  them (SQLite reports it as a read without a column; it cannot be told from a direct count, so it is allowed).
- **Data sources are registered by name** (`Limits.data_sources`), the node has a choice *Data source* and no field for a path.
  Today there is one, `app`. An extension can register its own SQLite file, with its own list of readable views and its own
  denials; the node needs no change. A manifest lists the choices it offers (`options`).
- **The result is JSON** like the Postgres node's: `rows`, `columns`, `row_count`, `truncated`, and the rows as the output.

## 3. Consequences

- A health check can be a Code node or an Agent (with the tool) that reads the views, or a plain query with a rule on the result.
  The events of a running agent step (tool calls, times) are only in the views for a finished step until the event log (card #100)
  is written during the run.
- The views are an interface that is documented and kept stable: a migration that changes a table behind a view keeps the view
  working. Changing a view's columns is a change of the interface.
- Safe by construction does not mean harmless: a long query can still cost time (the limit bounds it), and a view shows titles and
  numbers of every artifact. The author of the guard action decides what leaves the action (it is a normal action).

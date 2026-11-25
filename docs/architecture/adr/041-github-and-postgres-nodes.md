# ADR-041: The GitHub node and Postgres: an action node and a tool for agents

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-040](040-agent-tools.md), [ADR-012](012-workflow-definition-editor.md), [ADR-020](020-sqlite-stays-postgres-as-data-source.md)  
**Amended by:** —  
**Implemented in:** migration `0036_github_and_postgres_nodes`; `graph/node_types.py` (`GithubType`, `PostgresType`, `PostgresToolType`), `engine/github_runner.py`, `engine/postgres_runner.py`, `engine/executors.py` (`_github`, `_postgres`), `agents/local_tools.py` (`build_postgres_tool`); the editor (`static/js/editor/node-types.js`, `templates/components/icons.html`)

## 1. Title

Two more n8n building blocks: a **GitHub** node (read, and comment) and **Postgres** as an action node and as a tool of
an agent.

## 2. Context

The owner takes n8n as the model. With ADR-040 an agent reaches GitHub through GitHub's MCP server; what is missing is a
step of a flow that works without a model (n8n's GitHub node) and a way to read a Postgres database, as a step and as a
tool of an agent (n8n's Postgres node and Postgres tool). SQLite stays the application's own database
([ADR-020](020-sqlite-stays-postgres-as-data-source.md)); Postgres only comes as a connector to someone else's data. Lists matter:
a later Loop (postponed by the owner) iterates over a list a node returns, so these nodes return lists as lists.

## 3. Decision

### 3.1 The GitHub node (`github`)

- An execution node (On Pass / On Fail) of action definitions, no model. It calls the GitHub REST API through the
  guarded HTTP path (SSRF rules, pinned addresses, no redirects, capped body); no new dependency. The token is a secret
  named in the node (*Secret with the token*, empty: no token, public data only). *API address* defaults to
  `https://api.github.com` (GitHub Enterprise: its API address). A private address (an Enterprise server on the
  internal network) needs the operator's `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS`, as the HTTP node does.
- One select *Operation*, as n8n's resource and operation in one: `Get repository`, `List issues`, `Get issue`,
  `List pull requests`, `Get pull request`, `Get pull request diff`, `List pull request files`, `Get file`,
  `List comments`, `Create comment`. Settings that an operation does not use are ignored: *Repository* (`owner/name`),
  *Number*, *Path*, *Ref*, *State*, *Limit* (1 to 100, one page), *Comment*. Texts take `${node...}` and `${var...}`
  references; every value is validated or percent-encoded before it becomes a part of the URL.
- **Read, and comment; nothing else.** `Create comment` (on an issue or pull request) is the only write. It needs the
  switch *Allow comments* (off by default); a node with it off fails with a reason instead of writing.
- **Shape.** The node returns a curated subset of each GitHub object (the API's objects are large and full of URLs): in
  `data`, a single object is the object itself (`${node.X.data.title}`), a list is `{"items": [...], "count": n,
  "truncated": bool}`; `output` is the JSON of it (a file's text and a diff's text are the output as they are). Long
  bodies are cut. The list of issues does not contain pull requests (GitHub's API mixes them).

### 3.2 Postgres: one core, a node and a tool

- **One executor core** (`engine/postgres_runner.py`) runs one SQL statement and is used by both. The **Postgres node**
  (`postgres`, an execution node) takes its values from references; the **Postgres Tool** (`postgres_tool`, a tool kind
  of ADR-040) takes them from the model.
- **Connection.** One secret holds the connection URL (`postgresql://user:password@host:5432/db?sslmode=require`); the
  node and the snapshot only hold the secret's name, and the URL and the password are masked in results, details, logs
  and error texts. Only the keys `host`, `port`, `dbname`, `user`, `password`, `sslmode`, `connect_timeout` and
  `application_name` are accepted: no several hosts, no socket, no `options`, `service` or files.
- **Network.** The host is resolved here and every address vetted like the HTTP node's (metadata, unspecified and
  multicast addresses never; private addresses only with the node's *Private network* switch **and** the operator's
  switch). The connection goes to the vetted address (`hostaddr`), the name stays the TLS name. The node follows the
  HTTP node's operator switch (`OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS`), the tool the LLM providers' one
  (`OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS`), as ADR-040 has it for the HTTP Request Tool.
- **Values are bind parameters.** The SQL is written by the person who builds the flow and uses `$1`, `$2`, ...; the values
  (a line each for the node, the declared parameters in order for the tool) travel as parameters of the extended
  protocol and are never put into the text of the statement. One statement only, forced by the extended protocol.
- **Read-only by default, enforced by the server.** The statement runs in a `READ ONLY` transaction that is rolled back;
  a first query has run before the user's statement so that the mode cannot be changed back from inside it (checked
  against a real server: `SET TRANSACTION READ WRITE`, `set_config` and a `DO` block are refused). The switch *Allow
  changes* (off by default) lets the statement write; its transaction is committed when the statement succeeds. It is no
  substitute for a database role with the right privileges, which the documentation recommends.
- **Bounds.** A statement timeout on the server, the node's time limit around everything (a running statement is
  cancelled), at most *Max rows* (1 to 1000, default 100) and at most 48 KiB of result for the node, 15 KiB for the tool;
  what does not fit is left out and `truncated` is true. A read-only statement is read row by row and cancelled when
  the limit is reached, so a huge result is never held in memory. A statement that may change data is run to its end
  by the server (it is committed whole) and its answer is cut afterwards; it also reports how many rows it changed
  (`row_count`), which a read-only statement cannot.
- **Shape.** `data` is `{"rows": [...], "columns": [...], "row_count": n, "truncated": bool}`, `output` the rows as
  JSON (`columns` is empty for a read-only statement that returns no row). Values become JSON: numbers and text as they
  are, decimals as text, dates as ISO text, `bytea` as `\x...` text, JSON columns as JSON. The tool answers the model
  with `{"rows": [...], "row_count": n, "truncated": bool}`.
- **Driver.** `psycopg` 3 (async, binary) is a dependency of the application.

### 3.3 In the editor and the graph

Kinds `github` and `postgres` are execution nodes, `postgres_tool` hangs below an Agent node like the other tools;
migration `0036` adds the three kinds to the kind check (its downgrade deletes the nodes and their edges).

## 4. Consequences

- A flow can read issues and pull requests and comment without a model; an agent can look things up in a database with a
  query the flow's author wrote.
- Not built: other GitHub writes (create issues, labels, files), paging beyond one page, a query the model writes
  itself, Postgres notifications or transactions over several statements, other databases.
- The connection is opened per call; no pool.

## 5. Addendum (2026-11-25): the GitHub MCP node, and the token as a credential

- **The GitHub node** names its token by a **credential** (type *GitHub access token*, classic or fine-grained), chosen in the node
  with a pencil that opens the credentials window and *Create new credential* as the last entry. The address of a GitHub
  Enterprise server is a field of that credential (*GitHub server*), no longer a setting of the node. Resource and
  Operation are two choices side by side (what is not built yet is shown greyed and cannot be chosen); a setting is only drawn
  for the operations that use it (`shown_when`, `options_by`, `disabled_options`, `line` in the node manifests).
- **The GitHub MCP node** (`github_tool`, migration `0053`) hangs below an Agent node like the other tools and gives the agent
  every tool of GitHub's MCP server (`https://api.githubcopilot.com/mcp/`) to use on its own ("review issue 277", "summarise the
  state of the repository", "which points of the card are missing in the repo"). Its settings are the credential, *Allow writes*
  (off), the name for the model and a timeout. **Read-only until the switch is on**: the connection carries
  `X-MCP-Readonly: true`, and tools the server announces as changing something (`readOnlyHint` false) are left out as a second
  line. What the token may do on GitHub is also the limit of what the agent may do with *Allow writes* on.

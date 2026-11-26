# ADR-023: Safety model of execution nodes

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-008](008-security-operations.md), [ADR-017](017-request-hardening-and-signed-sessions.md)  
**Amended by:** [ADR-075](075-execute-command-node.md)  
**Implemented in:** `engine/code_runner.py`, `engine/code_registry.py`, `engine/http_runner.py`, `config.py` (settings `code_*`, `http_*`, key length), the start-up checks of `security.py`; no migration  
**Affected chapters:** [08.05](../arc42/08-cross-cutting-concepts/08.05-execution-nodes-safety.md), [08.01](../arc42/08-cross-cutting-concepts/08.01-security.md), [07](../arc42/07-deployment-view.md); guide [security](../../guides/security.md); [SECURITY.md](../../../SECURITY.md)

## 1. Title

What protects the application from the nodes that run code and call networks, and what does not.

## 2. Context

Code nodes run text written in the editor as a process of the application's user; HTTP nodes send requests to
addresses chosen by whoever edits a pipeline. In the one-container deployment (ADR-007, ADR-020) there is no
sandbox, no separate user and no network isolation to build on. The decision is what protection is built, who may
use the nodes, and how that is stated without overselling it.

## 3. Decision

### 3.1 Who may run Code nodes

Code nodes run only when an API token is set (`OPENARTIFACT_API_TOKEN`). Without a token the application is open
to everyone who can reach it, so a Code node would be remote code execution for them. In open mode a Code node
fails with a clear reason, unless `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true`, an explicit opt-in for local
development. `OPENARTIFACT_CODE_NODES_ENABLED=false` forbids Code nodes altogether. Anyone who may edit a pipeline
and start it is an operator of the application, not a user of a sandbox.

### 3.2 Code nodes: limits, not isolation

- The code is written to a private directory and run by `sh` or the application's own Python (`-I`) as a child
  process, in its own process group; a timeout or a stopped run ends the whole group.
- A small wrapper sets `RLIMIT_CPU` (timeout plus a margin), `RLIMIT_AS`, `RLIMIT_NPROC`, `RLIMIT_FSIZE`,
  `RLIMIT_NOFILE` and no core files, then replaces itself by the real process (no `preexec_fn`). If a limit cannot
  be applied the node fails instead of running unlimited. `PR_SET_PDEATHSIG` ends the child when the application is
  killed hard; `code_registry` ends leftovers of the process group at the next start.
- The environment holds `PATH`, `LANG`, `HOME`, the secrets the node asked for and one random marker; never an
  application setting. Output is bounded (`OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES`).
- The application sets `PR_SET_DUMPABLE` to 0 on itself (when the first Code process is started), which hardens it against being read by its own children:
  a code process cannot read the parent's `/proc/<pid>/environ` (where the token and the secret key live).
  This is hardening, not a sandbox.

### 3.3 HTTP nodes: a guarded request

The host name is resolved by the application, every address is checked and the request goes to the checked
address (the `Host` header and TLS server name stay the original), which removes the gap DNS rebinding needs.
Redirects are never followed, proxies from the environment are ignored, the response is read only up to a limit,
cloud metadata addresses are always refused, and private networks only with
`OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS=true`.

### 3.4 Secret key

`OPENARTIFACT_SECRET_KEY` must be at least 32 characters when a token is set or credentials are stored (ADR-024).

## 4. Consequences

- The limits protect against mistakes and resource exhaustion, not against malicious code: there is no network or
  filesystem isolation, the code runs as the application's user, and the memory and process limits are per process
  and per user, not a cgroup. A Code node can reach every address the application can, including internal
  services that HTTP nodes refuse.
- A deployment that must run untrusted code needs isolation outside the application (a separate container or
  host); that is not built.
- Windows or a system without the `resource` module runs code without limits and says so in the result.
- Open mode cannot run Code nodes by default, which costs convenience on a first local trial and is the intended
  trade.

## Update (2026-11-26): off by default, honest name

[ADR-075](075-execute-command-node.md): the node is called *Execute Command* (the kind id stays `code`), `OPENARTIFACT_CODE_NODES_ENABLED` is `false`
unless set, and a node may set an output limit of its own below the instance's.

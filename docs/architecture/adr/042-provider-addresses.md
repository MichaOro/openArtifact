# ADR-042: The address of an LLM provider is just an address

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-037](037-agent-harness.md) (the two permissions for private addresses)  
**Implemented in:** migration 0037 (`llm_providers.allow_private` becomes `allow_http`); `agents/providers.py` (`check_encryption`), `agents/client.py` (`UNENCRYPTED_REFUSED`), `agents/runtime.py` (`endpoint_of`, `run_node`); `static/js/agents/providers-page.js`  
**Affected chapters:** guides [agents](../../guides/agents.md), [security](../../guides/security.md), [configuration](../../guides/configuration.md), [API reference](../../guides/api-reference.md)

## 1. Context

ADR-037 made a provider on a private or local address depend on two permissions: the operator's
`OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS` and a switch on the provider. In practice that meant setting an environment
variable and restarting before an owner could enter `http://127.0.0.1:4000/v1` of their own LiteLLM. What the owner has
to confirm is not "private" but that the connection has no TLS.

## 2. Decision

- A provider may be on **any address**, public or local, without a setting of the operator and without a switch of the
  provider. Cloud metadata addresses stay refused, redirects are not followed, the connection goes to the address that
  was checked, and a provider is still saved only after its connection test got an OpenAI-shaped answer.
- An **`http://` address needs `allow_http`** (the tick *Allow unencrypted connection (HTTP)*), the owner's confirmation
  that the key and the prompts travel unencrypted knowingly. It is refused with 422 at save and test, and a node whose
  frozen provider is `http` without it fails before any request. The editor shows the tick only for an `http` address.
- OpenRouter keeps its fixed public address.
- `OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS` stays, for the tools of an agent only (MCP, HTTP Request, Postgres), which are
  not vetted by a test the way a provider is.
- Migration 0037 replaces the column; a provider whose address is `http` is confirmed by the upgrade so that it keeps
  working. It uses `ALTER TABLE` (a rebuild of the table would lose the case-insensitive name collation).

## 3. Consequences

- Whoever may create providers can have the application request any address; it is stored only when that address
  answers like an OpenAI API. This is accepted for an application with a login and one owner; the guide says so.
- From a container `127.0.0.1` is the container: a model server on the host needs a shared Docker network or
  `host.docker.internal`.

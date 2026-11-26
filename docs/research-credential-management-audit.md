# Research Report: OpenArtifact – Credentials & Secret Management Architecture Audit

**Date:** 2026-11-23  
**Status:** Research & Analysis only — no implementation performed  
**Scope:** Complete audit of existing secret architecture, credential usage, APIs, security model, and proposal for central credential management

---

## 1. Executive Summary

OpenArtifact **already has a fully functional secret store** (ADR-024, migration 0022) that provides:

- **Encrypted storage** of named secrets in a `secrets` table (AES-256-GCM, key derived via HKDF-SHA256 from `OPENARTIFACT_SECRET_KEY`)
- **API-only management** (`/api/secrets`, `/api/v1/secrets`) — list, create/replace, delete; values never returned
- **Node integration** — HTTP, Code, GitHub, Postgres, MCP Tool, HTTP Tool, Code Tool, Postgres Tool all reference secrets by name
- **Masking** — output, logs, and results are scrubbed for secret values in multiple forms (raw, percent-encoded, Base64, JSON-escaped)
- **Usage tracking** — `GET /api/secrets/{name}/uses` lists every node (and calling pipelines) that references a secret
- **MCP integration** — `list_secrets` tool exposes names only

**What is missing** (explicitly documented in `docs/guides/credentials.md` §107-113):
- **No user interface** for credentials (list, create, edit, delete, "used by")
- **No per-secret permissions**, audit log, expiry, or versioning
- **No way to read a value back** (by design)
- **No first-class credential types** — only generic "secret" names exist; providers/nodes just reference a name
- **No credential-type metadata** (e.g., "GitHub PAT", "PostgreSQL connection", "OpenRouter API key")

The architecture is **sound and secure for what it does**, but it is a **low-level secret store**, not a credential management system. The task ahead is to build a credential abstraction layer *on top* of this store.

---

## 2. Existing Secret Architecture (Untersuchungsbereich A)

### 2.1 Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **Database model** | `openartifact/models/credentials.py:17-35` | `Secret` table: `id` (UUID), `name` (unique, `[A-Z][A-Z0-9_]{0,63}`), `value` (encrypted blob), `created_at`, `updated_at` |
| **Migration** | `alembic/versions/0022_secrets.py` | Creates `secrets` table with unique index on `name` |
| **Crypto** | `openartifact/credentials/crypto.py` | AES-256-GCM via `cryptography`; HKDF-SHA256 key derivation; nonce = 96-bit random; name as AAD |
| **Store** | `openartifact/credentials/store.py` | `SecretStore` class: `names()`, `put()`, `delete()`, `resolve()`, `uses()` |
| **References & Masking** | `openartifact/credentials/refs.py` | `${secret:NAME}` syntax, substitution, validation, masking (`***`) |
| **Browser API** | `openartifact/api/secrets.py` | `GET /api/secrets`, `PUT /api/secrets/{name}`, `DELETE /api/secrets/{name}`, `GET /api/secrets/{name}/uses` |
| **Integration API** | `openartifact/api/v1.py:375-406` | Same operations under `/api/v1/secrets` (token-protected) |
| **MCP Tool** | `openartifact/api/mcp.py` (via `build_mcp`) | `list_secrets` tool — names only |

### 2.2 Encryption Details

- **Algorithm:** AES-256-GCM (authenticated encryption)
- **Key derivation:** HKDF-SHA256(`OPENARTIFACT_SECRET_KEY`, salt=None, info=`b"openartifact/secret-store/v1"`)
- **Nonce:** Fresh 96-bit random per encryption
- **Associated Data (AAD):** The secret **name** — prevents ciphertext relocation attacks
- **Stored format:** `version_byte(0x01) | nonce(12) | ciphertext+tag`
- **Limits:** 8 KiB max per secret value; NUL bytes rejected

### 2.3 Secret Lifecycle

```
PUT /api/secrets/{name}  → validate name + value → encrypt(settings.secret_key, name, value)
                          → INSERT or UPDATE secrets table (value = blob)
                          → return SecretRead (name, created_at, updated_at)  ← NEVER the value

GET /api/secrets         → SELECT name, created_at, updated_at FROM secrets ORDER BY name
                          → return list[SecretRead]

DELETE /api/secrets/{name} → SELECT → DELETE → 204 (404 if not found)

resolve(names[])         → SELECT name, value FROM secrets WHERE name IN (...)
                          → decrypt each with settings.secret_key + name as AAD
                          → return {name: plaintext}  ← ONLY executors call this
```

### 2.4 Secret Resolution at Runtime

- **Executors** (`openartifact/engine/executors.py`) receive `Limits.secrets: SecretResolver | None`
- Each executor (`_code`, `_http`, `_postgres`, `_github`, `_agent`) extracts secret names from node config
- Calls `_with_secrets(names, limits, run_fn)` → resolves → runs node → **masks all outputs**
- **Snapshots** (frozen pipeline graphs) store **only names** — never values

### 2.5 Access Control

- **Writing secrets** requires both:
  - `OPENARTIFACT_API_TOKEN` set (≥32 chars)
  - `OPENARTIFACT_SECRET_KEY` set to non-default value (≥32 chars)
- Without these, `SecretStore.writable == False` → `409 "Set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY first"`
- **Reading secrets** (resolve) only happens in executors during node execution — no API endpoint returns values
- **MCP server** only exposes `list_secrets` (names)

### 2.6 Usage Tracking (`uses` endpoint)

`SecretStore.uses(name)` queries `GraphNode` joined with `Graph` for nodes of kinds:
- `CODE`, `HTTP`, `GITHUB`, `POSTGRES`, `MCP_TOOL`, `HTTP_TOOL`, `CODE_TOOL`, `POSTGRES_TOOL`

Extracts referenced secret names from node config:
- Code/Code Tool: `config.secrets` (one per line)
- GitHub/Postgres/MCP Tool/Postgres Tool: `config.secret` (single name)
- HTTP/HTTP Tool: `${secret:NAME}` in `url`, `headers`, `body`

Returns `SecretUse` with node details + calling pipelines (action definitions referenced by pipeline nodes).

---

## 3. Current Credential Usage by Component (Untersuchungsbereich B)

| Component | Credential Type | Current Storage | Secret Store Bound? |
|-----------|-----------------|-----------------|---------------------|
| **LLM Provider (OpenRouter)** | API Key | Provider stores `secret_name` → resolves via `SecretStore` at runtime | ✅ Yes |
| **LLM Provider (OpenAI-compatible)** | API Key | Provider stores `secret_name` → resolves via `SecretStore` at runtime | ✅ Yes |
| **HTTP Node** | Bearer Token / API Key / any header/body/URL value | `${secret:NAME}` references in `url`, `headers`, `body` config | ✅ Yes |
| **HTTP Request Tool** | Bearer Token / API Key | Same as HTTP node (model fills `{param}`, secrets via `${secret:NAME}`) | ✅ Yes |
| **MCP Client Tool** | Bearer Token (Authorization header) | `config.secret` (single name) | ✅ Yes |
| **GitHub Node** | Personal Access Token | `config.secret` (single name) | ✅ Yes |
| **GitHub MCP (via MCP Tool)** | PAT / OAuth token | MCP Tool `config.secret` | ✅ Yes |
| **Postgres Node** | Connection URL (`postgresql://user:pass@host/db`) | `config.secret` (single name holding full URL) | ✅ Yes |
| **Postgres Tool** | Connection URL | `config.secret` (single name) | ✅ Yes |
| **Code Node** | Any env vars (API keys, passwords, tokens) | `config.secrets` (list of names, one per line) | ✅ Yes |
| **Code Tool** | Any env vars | `config.secrets` (list of names) | ✅ Yes |
| **Agent Node** | LLM Provider key (via provider) + Tool secrets | Provider `secret_name` + Tool `secret` references | ✅ Yes |

**Key finding:** *All* credential-consuming components already use the secret store **by name reference only**. No component stores plaintext credentials in its config.

---

## 4. Data Models & APIs (Untersuchungsbereich C)

### 4.1 Secret Data Model

```python
# openartifact/models/credentials.py
class Secret(Base):
    __tablename__ = "secrets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)      # UUID
    name: Mapped[str] = mapped_column(String(64), unique=True)         # [A-Z][A-Z0-9_]{0,63}
    value: Mapped[bytes] = mapped_column(LargeBinary)                  # encrypted blob
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### 4.2 Provider Model (references secret by name)

```python
# openartifact/models/agents.py
class LlmProvider(Base):
    secret_name: Mapped[str | None] = mapped_column(String(64), nullable=True)  # name only
    # ... never stores the key itself
```

### 4.3 Node Config References

| Node Kind | Config Field | Reference Style |
|-----------|--------------|-----------------|
| Code / Code Tool | `secrets` | List of names (one per line) |
| HTTP / HTTP Tool | `url`, `headers`, `body` | `${secret:NAME}` inline |
| GitHub / MCP Tool / Postgres / Postgres Tool | `secret` | Single name |

### 4.4 API Endpoints

| Endpoint | Method | Purpose | Returns Value? |
|----------|--------|---------|----------------|
| `/api/secrets` | GET | List all secrets (names + dates) | ❌ No |
| `/api/secrets/{name}` | PUT | Create or replace secret | ❌ No (201/200 + metadata) |
| `/api/secrets/{name}` | DELETE | Delete secret | ❌ No |
| `/api/secrets/{name}/uses` | GET | List referencing nodes + pipelines | ❌ No |
| `/api/v1/secrets` | GET | Integration API: list | ❌ No |
| `/api/v1/secrets/{name}` | PUT | Integration API: create/replace | ❌ No |
| `/api/v1/secrets/{name}` | DELETE | Integration API: delete | ❌ No |
| MCP `list_secrets` | tool | MCP: list names | ❌ No |

### 4.5 Answers to Specific Questions

1. **Can a secret be reused by multiple components?**  
   ✅ **Yes** — `uses` endpoint proves this; any number of nodes/providers can reference the same secret name.

2. **Stable Secret ID or name-based reference?**  
   **Name-based** — nodes store the secret **name** (string), not the UUID. The `id` is internal only.

3. **Can nodes access secrets without receiving plaintext?**  
   ❌ **No** — executors *do* decrypt and pass plaintext to the node process (env var for Code, header/body for HTTP, etc.). This is by design: the node *needs* the value to function. Masking protects outputs/logs, not the node's runtime access.

4. **Can you find which components use a secret?**  
   ✅ **Yes** — `GET /api/secrets/{name}/uses` returns all referencing nodes and their calling pipelines.

5. **What happens when a used secret is deleted?**  
   Node execution fails with `"Secret NAME does not exist"` (handled in `_with_secrets` → `SecretResolveError`).

6. **Can credentials be updated without changing referencing nodes?**  
   ✅ **Yes** — `PUT /api/secrets/{name}` replaces the value; all nodes immediately use the new value on next run.

---

## 5. Security Analysis (Untersuchungsbereich D)

### 5.1 Proven Security Mechanisms

| Mechanism | Implementation | Status |
|-----------|----------------|--------|
| **Encryption at rest** | AES-256-GCM, HKDF-SHA256 key derivation, per-value nonce, name as AAD | ✅ Implemented |
| **No value in API responses** | All endpoints return `SecretRead` (name, dates only) | ✅ Implemented |
| **Masking in outputs/logs** | `mask_text` / `mask_data` replace all common forms (raw, %XX, Base64, JSON) | ✅ Implemented |
| **Log filtering** | `logging_config._SensitiveFilter` masks API token, secret key, and secret values during node execution | ✅ Implemented |
| **Snapshot safety** | Frozen graphs store only secret names | ✅ Implemented |
| **Access gate** | `AccessGate` middleware requires API token (or session) for all non-open paths | ✅ Implemented |
| **Process memory protection** | `prctl(PR_SET_DUMPABLE, 0)` on Linux prevents child Code nodes from reading parent env | ✅ Implemented |
| **Secret key separation** | Derived key for encryption ≠ session cookie signing key | ✅ Implemented |

### 5.2 Missing / Incomplete Security Mechanisms

| Mechanism | Status | Risk |
|-----------|--------|------|
| **Key rotation / re-encryption** | ❌ Not implemented — changing `SECRET_KEY` makes all secrets unreadable | High (operational risk) |
| **Per-secret permissions** | ❌ No RBAC — anyone with API token can read/use all secrets | Medium |
| **Audit log** | ❌ No record of who created/read/deleted a secret | Medium |
| **Secret expiry / TTL** | ❌ Not supported | Low |
| **Secret versioning** | ❌ Not supported (PUT replaces) | Low |
| **Backup key separation** | ⚠️ Doc warns: "Keep the key out of the backup of the data volume" | Operational |
| **Code node escape** | ⚠️ Doc admits: "A node that is allowed to read a secret can always leak it on purpose" | Inherent (Code nodes run as app user) |
| **Database file permissions** | ⚠️ ADR-008 "file permissions 600" not enforced by app | Operational |

### 5.3 Unverifiable Properties

- **Key storage security** — depends on deployment (env var, file, secret manager); app does not manage this
- **Network encryption** — TLS termination is external; `http_allow_private_networks` controls SSRF but not transit encryption
- **MCP server token handling** — token passed in `Authorization: Bearer` header; relies on TLS

### 5.4 Risk Summary

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Secret key loss → all secrets lost | Low (if backed up) | Critical | Document rotation procedure; test restore |
| Compromised DB + key → all secrets exposed | Low (needs both) | Critical | Separate key storage; restrict DB access |
| Code node exfiltrates secret | Medium (if untrusted users edit actions) | High | Treat "can edit actions" = "can read all secrets" |
| Secret leaked in logs despite masking | Low (value-based masking) | Medium | Masking covers common forms; test with odd encodings |

---

## 6. Missing Functionality (Untersuchungsbereich E vs. Current)

| n8n-style Credential Feature | Current State | Gap |
|------------------------------|---------------|-----|
| **Credential Types** (GitHub PAT, PostgreSQL, OpenRouter, Generic API Key, etc.) | ❌ Only generic "secret name" | No type metadata, no validation per type |
| **UI: List credentials** | ❌ API only | No page, no table, no search/filter |
| **UI: Create credential** | ❌ API only | No form, no type selection, no test button |
| **UI: Edit credential** | ❌ PUT replaces value | No "update" distinction, no version history |
| **UI: Delete credential** | ❌ API only | No confirmation with "used by" preview |
| **UI: Test credential** | ✅ Provider test does this for LLM keys | Not generalized; no "test" for HTTP/Postgres/GitHub |
| **UI: Show usages** | ✅ `/uses` endpoint exists | Not surfaced in UI |
| **Credential reuse across nodes** | ✅ Works via name | No UI to pick from list in node inspector |
| **Credential rotation** | ❌ Manual PUT + hope | No assisted rotation, no overlap period |
| **Credential deactivation** | ❌ Only delete | No "disable" flag |
| **Folders / tags / projects** | ❌ Flat namespace | No organization |

---

## 7. Central Credential Management Concept (Untersuchungsbereich E)

### 7.1 Credential Types Worth Modeling

| Type | Fields | Validation | Test Strategy |
|------|--------|------------|---------------|
| **Generic API Key** | `name`, `api_key` | Non-empty | Optional: HEAD request to known endpoint |
| **Bearer Token** | `name`, `token` | Non-empty | Optional: authenticated request to test URL |
| **GitHub PAT** | `name`, `token` | `ghp_` / `github_pat_` prefix? | `GET /user` via GitHub API |
| **OpenRouter API Key** | `name`, `api_key` | Non-empty | `/models` via OpenRouter |
| **OpenAI-compatible Key** | `name`, `api_key`, `base_url` | URL + non-empty key | `/models` or test completion |
| **PostgreSQL Connection** | `name`, `url` (`postgresql://...`) | Valid URL, parses to host/port/db/user/pass | `SELECT 1` |
| **MCP Auth** | `name`, `token` | Non-empty | Initialize MCP session |
| **Username/Password** | `name`, `username`, `password` | Both non-empty | Depends on target |

### 7.2 Required UI Functions

| Function | Priority | Backend Support |
|----------|----------|-----------------|
| List credentials (with type badge, last used, status) | **Must** | `names()` + new metadata |
| Create credential (type selector → type-specific form) | **Must** | New `put_credential(type, name, fields)` |
| Edit credential (update fields, rotate value) | **Must** | New `update_credential` |
| Delete credential (with usage warning) | **Must** | `delete()` + `uses()` |
| Test credential | **Should** | Type-specific test endpoints |
| Show usages (nodes, pipelines, providers) | **Should** | `uses()` + provider references |
| Deactivate/activate | **Could** | New `enabled` flag on credential |
| Rotation assistant (old + new overlap) | **Could** | Versioned values or dual-write |

---

## 8. Integration into OpenArtifact (Untersuchungsbereich F)

### 8.1 Navigation Placement

| Option | Pros | Cons |
|--------|------|------|
| **Top-level "Credentials" menu item** | Discoverable; matches n8n; first-class feature | Crowds navigation if many items |
| **Under "Settings" → "Credentials"** | Logical grouping; less clutter | Less discoverable; users expect standalone |

**Recommendation:** Top-level menu item **"Credentials"** (icon: key), placed after **"Agents"** — it's a core operational feature, not a rare setting.

### 8.2 Node Inspector Integration

Current: Node inspectors show raw config fields (text input for `secret` name, lines for `secrets`).

**Proposed:** Add a **credential picker** component:
- Button "🔑 Select Credential" next to secret name field
- Opens modal with searchable list of credentials (filtered by compatible type)
- On select: writes credential name into field
- For HTTP nodes: insert `${secret:NAME}` at cursor in URL/headers/body

### 8.3 Reference Storage

- **Node config** continues to store **only the secret name** (string)
- **Credential metadata** (type, description, test status) lives in new `credentials` table
- **Secret value** remains in existing `secrets` table (unchanged)

### 8.4 Execution Resolution

No change needed — executors already call `SecretStore.resolve(names)` which reads from `secrets` table. The credential abstraction only adds metadata on top.

---

## 9. Architecture Variants (Untersuchungsbereich H)

### Variant A: Extend Existing Secret Store

**Approach:** Add credential metadata columns to `secrets` table (or 1:1 `credentials` table joined to `secrets`).

| Aspect | Assessment |
|--------|------------|
| **Complexity** | Low — single table or tight join |
| **Reusability** | High — secrets stay the storage layer |
| **Extensibility** | Medium — type-specific fields need JSON column or EAV |
| **Security model** | Unchanged — encryption, masking, resolution identical |
| **Migration effort** | Low — ALTER TABLE or new table with FK |
| **API effort** | Medium — new endpoints for credential CRUD + type registry |
| **UI effort** | Medium — new page, forms per type, picker component |
| **Impact on existing nodes** | None — they still reference secret name |

**Implementation sketch:**
```sql
-- Option 1: Extend secrets table
ALTER TABLE secrets ADD COLUMN credential_type VARCHAR(32);
ALTER TABLE secrets ADD COLUMN credential_meta JSON;  -- type-specific fields
ALTER TABLE secrets ADD COLUMN description TEXT;
ALTER TABLE secrets ADD COLUMN enabled BOOLEAN DEFAULT true;
```

### Variant B: Independent Credential Abstraction Layer

**Approach:** New `credentials` table (metadata, type, description, enabled, etc.) with FK to `secrets.id` (or `secrets.name`). The secret store remains pure storage; credential service handles types, validation, testing, UI.

| Aspect | Assessment |
|--------|------------|
| **Complexity** | Medium — new service, table, API, but cleaner separation |
| **Reusability** | High — credential types pluggable; secret store untouched |
| **Extensibility** | High — new types = new validation/test handlers, no schema migration |
| **Security model** | Unchanged — secret store still does encryption/resolution |
| **Migration effort** | Medium — new table, data migration for existing secrets |
| **API effort** | Medium — credential service + API, but secret API unchanged |
| **UI effort** | Medium — same as Variant A |
| **Impact on existing nodes** | None — they reference secret name; credential resolves to secret |

**Implementation sketch:**
```sql
CREATE TABLE credentials (
    id UUID PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,           -- same namespace as secrets
    secret_id UUID REFERENCES secrets(id),      -- FK to secret store
    type VARCHAR(32) NOT NULL,                  -- 'github_pat', 'postgres_url', 'generic_api_key', ...
    meta JSON NOT NULL DEFAULT '{}',            -- type-specific config (e.g., base_url for OpenAI-compatible)
    description TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    tested_at TIMESTAMP,
    test_ok BOOLEAN,
    test_message TEXT
);
```

### 9.3 Comparison Summary

| Criterion | Variant A (Extend Store) | Variant B (Credential Layer) |
|-----------|--------------------------|------------------------------|
| **Architecture purity** | ❌ Mixes storage + metadata | ✅ Clean separation |
| **Type extensibility** | ⚠️ JSON column or migrations | ✅ New type = new handler |
| **Migration risk** | Low (ALTER TABLE) | Medium (new table + data copy) |
| **Secret store stability** | ❌ Changes to core table | ✅ Store untouched |
| **API surface** | Extended secret API | New credential API + unchanged secret API |
| **Backward compatibility** | ✅ Existing secrets work | ✅ Existing secrets work (link via name) |
| **Credential "test" feature** | Added to store | Natural in credential service |
| **Provider integration** | Provider → secret name | Provider → credential → secret |
| **Recommended** | ⚠️ Quick but less clean | ✅ **Preferred** for long-term growth |

**Recommendation: Variant B** — The credential abstraction belongs *above* the secret store, not inside it. The secret store is a **secure key-value blob store**; credentials are **typed, validated, testable, discoverable entities** that *use* the store. This matches n8n's architecture and keeps the security-critical crypto code small and unchanged.

---

## 10. Impact Analysis (Untersuchungsbereich G)

| Component | Current State | Expected Adaptation | Risk |
|-----------|---------------|---------------------|------|
| **LLM Providers** | Store `secret_name` (string) | Optional: link to credential (type: `openrouter_key`, `openai_compatible_key`) for UI picker + test | Low — backward compatible |
| **HTTP Nodes / Tools** | `${secret:NAME}` inline | Credential picker inserts name; type filter shows `generic_api_key`, `bearer_token` | Low |
| **GitHub Node / MCP** | `secret` (single name) | Credential picker filters to `github_pat` | Low |
| **Postgres Nodes / Tools** | `secret` (connection URL) | Credential picker filters to `postgres_connection` | Low |
| **Code Nodes / Tools** | `secrets` (list of names) | Multi-select picker; type filter less relevant | Low |
| **Agent Nodes** | Provider `secret_name` + Tool `secret` | Provider UI shows credential picker; tools same as above | Low |
| **Execution Engine** | `SecretStore.resolve()` | **No change** — still resolves secret names to values | None |
| **Execution History / Snapshots** | Store secret names only | **No change** — names remain stable | None |
| **MCP Server** | `list_secrets` tool | Add `list_credentials` tool (metadata) | Low |
| **Published Agent Versions** | Frozen config with secret names | **No change** — names stable | None |

**Backward compatibility:** 100% — all existing nodes/providers/configs continue to work unchanged. Credential layer is *additive*.

---

## 11. Recommended Target Architecture

### 11.1 Core Principles

1. **Secret store remains unchanged** — it is the secure storage & resolution layer
2. **Credential = metadata + type + validation + test** — a thin layer *on top*
3. **Nodes/providers reference secret names** — no schema changes to node configs
4. **Credential types are pluggable** — registry pattern for validation/test handlers
5. **UI discovers credentials by type** — picker filters compatible types per node field

### 11.2 Data Model

```python
# New: openartifact/models/credentials.py (extends or new file)
class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # same namespace as secrets
    secret_id: Mapped[str] = mapped_column(String(36), ForeignKey("secrets.id"))  # FK
    type: Mapped[str] = mapped_column(String(32))  # e.g., "github_pat"
    meta: Mapped[dict] = mapped_column(JSON, default={})  # type-specific (base_url, etc.)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tested_at: Mapped[datetime | None]
    test_ok: Mapped[bool | None]
    test_message: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

### 11.3 Credential Type Registry

```python
# openartifact/credentials/types.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class CredentialType:
    key: str                    # "github_pat"
    label: str                  # "GitHub Personal Access Token"
    description: str
    fields: list[FieldSpec]     # UI form fields
    secret_fields: list[str]    # which fields go into the secret value
    test: TestHandler | None    # async function to validate

class TestHandler(ABC):
    @abstractmethod
    async def test(self, secret_value: str, meta: dict) -> TestResult: ...

REGISTRY: dict[str, CredentialType] = {}
def register_type(t: CredentialType): REGISTRY[t.key] = t
```

### 11.4 Service Layer

```python
# openartifact/credentials/credential_store.py
class CredentialStore:
    def __init__(self, session, settings, secret_store: SecretStore):
        ...
    async def create(self, type_key: str, name: str, fields: dict, description: str) -> CredentialRead
    async def update(self, name: str, fields: dict | None, description: str | None) -> CredentialRead
    async def delete(self, name: str) -> None
    async def test(self, name: str) -> TestResult
    async def list(self, type_filter: str | None = None) -> list[CredentialRead]
    async def get(self, name: str) -> CredentialRead
    async def usages(self, name: str) -> CredentialUses  # extends SecretStore.uses()
```

### 11.5 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/credentials` | GET | List credentials (with type, status, last test) |
| `/api/credentials` | POST | Create credential (type + fields → validates, tests, stores secret) |
| `/api/credentials/{name}` | GET | Get credential metadata |
| `/api/credentials/{name}` | PATCH | Update credential (fields, description, enabled) |
| `/api/credentials/{name}` | DELETE | Delete credential (checks usages) |
| `/api/credentials/{name}/test` | POST | Re-run connection test |
| `/api/credentials/{name}/uses` | GET | Combined usages (nodes + providers + agents) |
| `/api/credentials/types` | GET | List registered credential types (for UI form builder) |

---

## 12. Implementation Phases

| Phase | Scope | Deliverables | Est. Effort |
|-------|-------|--------------|-------------|
| **1. Foundation** | Credential model, migration, registry, basic CRUD service, API | `credentials` table, `CredentialStore`, `/api/credentials` (list, create, get, delete), 3-4 base types | Medium |
| **2. Type System** | Full type registry, validation, test handlers for all types | GitHub PAT, OpenRouter, OpenAI-compatible, Postgres, Generic API Key, Bearer Token, MCP Auth | Medium |
| **3. UI — List & Create** | Credentials page, type selector, dynamic forms, test button | `/credentials` route, list table, create modal, toast notifications | Medium |
| **4. UI — Edit & Usages** | Edit modal, delete confirmation with usages, rotation helper | Edit form, usages panel, "rotate" action (create new secret, update credential) | Medium |
| **5. Node Integration** | Credential picker component in inspectors | Picker button next to secret fields, filters by compatible type, inserts name | Medium |
| **6. Provider Integration** | Provider dialog uses credential picker | Link provider `secret_name` to credential; show credential status in provider card | Low |
| **7. Polish & Migration** | Migrate existing secrets → credentials (optional), docs, tests | One-time script to wrap existing secrets as `generic_api_key` credentials | Low |

**Total estimate:** 6-8 focused development sessions

---

## 13. Open Questions & Risks

| Question | Impact | Resolution Approach |
|----------|--------|---------------------|
| **Secret name ↔ Credential name namespace** | Shared or separate? | **Shared** — credential name = secret name; 1:1 mapping simplifies resolution |
| **Credential without secret?** (e.g., public GitHub) | Some types need no secret | Allow `secret_id` nullable; `enabled` flag controls usability |
| **Multiple secrets per credential?** (user+pass) | Postgres URL encodes both | For now: single secret holds full connection string; advanced: composite credentials later |
| **Credential versioning** | Rotation without downtime | Phase 4: "rotate" creates new secret, updates credential, keeps old for overlap |
| **Project/team scoping** | Multi-tenancy | Out of scope for v1; global namespace like current secrets |
| **Import/export** | Backup, migration | API supports it; CLI command later |

---

## 14. Final Recommendation

**How to build a central, reusable credential management from the existing secret store with minimal invasive changes?**

### Target Architecture: Variant B — Independent Credential Abstraction Layer

```
┌─────────────────────────────────────────────────────────────────┐
│                      UI LAYER                                   │
│  /credentials page  ──  Credential Picker (in node inspectors)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CREDENTIAL SERVICE                            │
│  CredentialStore: CRUD, types, validation, test, usages         │
│  Registry: GitHub PAT, OpenRouter, OpenAI-compatible, Postgres, │
│            Generic API Key, Bearer Token, MCP Auth, ...         │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│   SECRET STORE          │       │   PROVIDER / NODE       │
│   (unchanged)           │       │   CONFIG (unchanged)    │
│   - encrypt/decrypt     │       │   - secret_name: str    │
│   - resolve(names[])    │       │   - secret: str         │
│   - masking             │       │   - secrets: list[str]  │
│   - uses()              │       │   - ${secret:NAME}      │
└─────────────────────────┘       └─────────────────────────┘
```

### Implementation Order (Minimal Invasive)

1. **Add `credentials` table** (migration) — FK to `secrets.id`, `type`, `meta`, `description`, `enabled`, test fields
2. **Build `CredentialStore` service** — wraps `SecretStore` for secret ops; adds type registry, validation, test
3. **Expose `/api/credentials`** — list, create, get, update, delete, test, uses, types
4. **Register base credential types** — each with fields, validation, test handler
5. **Build UI** — list page, create/edit modals, type selector, test button, usages panel
6. **Add credential picker component** — reusable in provider dialog + node inspectors
7. **Wire provider dialog** — "Select Credential" button, shows compatible types, writes `secret_name`
8. **Wire node inspectors** — picker button next to secret fields, inserts name/`${secret:NAME}`
9. **Optional migration script** — wrap existing secrets as `generic_api_key` credentials for UI visibility

### Why This Works Long-Term

| Requirement | How It's Met |
|-------------|--------------|
| **Grows with new node types** | New node → uses secret name → credential picker shows compatible types |
| **Grows with new providers** | Provider type = credential type; test reuses credential test handler |
| **Grows with MCP integrations** | MCP auth = credential type; test initializes MCP session |
| **No breaking changes** | Existing nodes/providers/configs unchanged; secret store untouched |
| **Security unchanged** | Encryption, masking, resolution, access control all stay in secret store |
| **n8n-like UX** | Types, test, picker, usages — all built on proven patterns |

---

**End of Research Report**  
*No code was modified during this audit. All findings reference actual files and line numbers in the OpenArtifact codebase as of 2026-11-23.*
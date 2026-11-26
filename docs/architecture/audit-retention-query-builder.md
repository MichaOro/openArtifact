# Architecture & UX Audit: Retention Management & Generic Query Builder

**Date:** 2026-11-23  
**Status:** Audit only — no implementation, no code changes

---

## 1. Executive Summary

This audit examines two planned extensions for the Executions page:

1. **Configurable Retention Management** — enhance the existing per-artifact retention policy with global defaults, bulk operations, and policy templates.
2. **Generic Query Builder** — a reusable Visual Mode + Advanced Expression Editor for building complex filters across the application.

The repository already contains a mature execution history system (ADR-025, ADR-028) with per-artifact retention (`history_keep_last`, `history_keep_hours`), a global executions page with keyset paging and filters, bulk selection/deletion, and a clean component architecture. This audit evaluates how to extend these foundations with minimal invasion.

---

## 2. Existing Architecture Evidence

### 2.1 Retention Management (Current State)

| Aspect | Implementation |
|--------|----------------|
| **Data Model** | `tasks.history_keep_last` (1–1000), `tasks.history_keep_hours` (1–8760), `execution_seq` (ADR-025, migration 0023) |
| **Default Policy** | `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP` (default 50, `0` = unlimited) — applies when artifact has no policy |
| **Evaluation** | `ExecutionHistory.prune()` — runs on execution start/end, policy change; logical AND of limits; newest & running never auto-deleted |
| **API** | `PUT /api/tasks/{id}/history-policy` (browser), `PUT /api/v1/artifacts/{ref}/history-policy` (integration); body replaces whole policy |
| **UI** | `RetentionEditor` component (collapsible in History tab) — two number fields, live validation, shows deleted count |
| **Tests** | Truth-table parametrized tests covering all policy combinations (test_history.py:376–530) |

**Key ADRs:** ADR-025 (history & retention), ADR-028 (global executions page), ADR-027 (flow by replay)

### 2.2 Global Executions Page (Current State)

| Aspect | Implementation |
|--------|----------------|
| **Endpoint** | `GET /api/executions` (also `/api/v1/executions`, MCP `list_all_executions`) |
| **Filters** | `status`, `started_by`, `pipeline`, `q` (text search), `since`/`until`, `range` presets — all AND-combined |
| **Paging** | Keyset cursor over `(started_at DESC, id DESC)` — stable under inserts/deletes |
| **UI Components** | `FilterBar` (toggles, text fields, presets), `ExecutionTable`, `SummaryStrip`, `BulkBar`, `Selection` |
| **Bulk Delete** | `POST /api/executions/delete` — up to 500 IDs, skips running, reports `skipped_running` |
| **Live Updates** | SSE `execution.updated` / `execution.deleted` — in-place row updates, "new execution" hint |

**Key Files:**
- Backend: `engine/history_query.py` (filters, cursor, paging), `api/executions.py`
- Frontend: `static/js/executions/{page.js, filters.js, filter-bar.js, table.js, api.js}`
- Components: `static/js/components/{selection.js, bulk-bar.js}`

### 2.3 Reusable Component Patterns

| Component | Location | Reusability |
|-----------|----------|-------------|
| `Selection` | `components/selection.js` | Generic set of IDs + `stateOf(shown)` for "select all" checkbox |
| `BulkBar` | `components/bulk-bar.js` | Generic count + "Select all N" + clear + action button |
| `FilterBar` | `executions/filter-bar.js` | Executions-specific (status/origin toggles, pipeline, q, range) |
| `Filters` | `executions/filters.js` | Executions-specific value object + URL sync |
| `RetentionEditor` | `tasks/retention-editor.js` | Per-artifact policy editor |
| `ConfirmDialog` + `Modal` | `components/` | Generic confirmation flow |

### 2.4 API Conventions

- REST + OpenAPI (ADR-006), versioning via `/api/v1/`
- Pydantic models for request/response (`engine/schemas.py`)
- `ArtifactError` with `fieldErrors` for validation (422)
- SSE for live updates (`GET /api/events`)
- Keyset paging with base64url-encoded cursors

---

## 3. Requirements Analysis

### 3.1 Retention Management — Extended Scope

The audit request implies these enhancements beyond the existing per-artifact policy:

1. **Global default management** — UI to configure `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP` (currently env var only)
2. **Policy templates/presets** — "Keep last 10", "Keep 48 hours", "Keep last 5 + 24h", etc.
3. **Bulk policy application** — apply a policy to multiple artifacts at once (from the global executions page or board)
4. **Policy inheritance** — artifacts without explicit policy inherit global default (already implemented)
5. **Audit/preview** — show how many executions a policy change would delete before applying

### 3.2 Generic Query Builder — Scope

A reusable component for building filter expressions with two modes:

| Mode | Description |
|------|-------------|
| **Visual Mode** | Drag-drop or click-to-add conditions, grouped by field type, with operators per field (e.g., status: is one of, pipeline: contains, started: before/after) |
| **Advanced Expression Editor** | Text-based expression with syntax highlighting, autocomplete, validation — for power users |

**Reusability targets:** Global executions page (replaces `FilterBar`), artifact history tab, agent runs, secrets, board filters, future lists.

---

## 4. Audit Findings

### 4.1 Retention Management — Architecture Assessment

#### ✅ Strengths to Build On
1. **Policy evaluation is centralized** in `ExecutionHistory.prune()` — single source of truth
2. **Default fallback is already implemented** — `effective_default_keep` in `HistoryPolicy`
3. **API already supports full policy replacement** — `PUT /history-policy` with validation
4. **UI component exists** — `RetentionEditor` handles validation, dirty state, save flow
5. **Tests are comprehensive** — truth-table parametrization covers all combinations

#### ⚠️ Gaps for Extended Requirements

| Gap | Current State | Effort to Extend |
|-----|---------------|------------------|
| Global default UI | Env var only (`OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`) | Low — add `/api/settings/execution-history-default` + settings page |
| Policy templates | Not present | Medium — new API endpoint + UI picker; reuse `HistoryPolicyWrite` schema |
| Bulk policy apply | Not present | Medium — new `POST /api/tasks/bulk/history-policy` or similar; needs artifact selection |
| Preview before apply | Not present | Low — `prune()` logic is pure; can run in read-only transaction and return count |
| Policy inheritance UI | Implicit only | Low — `RetentionEditor` already shows effective default; add explicit "Use default" toggle |

#### 🔧 Recommended Approach (Minimal Invasion)

1. **Global default** — Add `execution_history_default_keep` to `Settings` model + `/api/settings/run-limits`-style endpoint + settings UI section. No schema changes.

2. **Policy templates** — Define as constants in `engine/schemas.py` (e.g., `RETENTION_TEMPLATES = [{name, keep_last, keep_hours}, ...]`). Add `GET /api/retention/templates` endpoint. UI: dropdown in `RetentionEditor` that pre-fills fields.

3. **Bulk apply** — Add `POST /api/tasks/bulk/history-policy` accepting `{task_ids: string[], policy: HistoryPolicyWrite}`. Reuse `ExecutionHistory.prune()` per artifact in a transaction. Frontend: add "Apply policy to selected" in global executions page bulk bar (reuse `Selection` + `BulkBar`).

4. **Preview** — Add `?preview=true` to `PUT /history-policy` that runs prune in a savepoint and rolls back, returning `would_delete`. Or new endpoint `POST /api/tasks/{id}/history-policy/preview`.

**No new tables, no migration needed.** All logic exists; only wiring.

---

### 4.2 Generic Query Builder — Architecture Assessment

#### ✅ Strengths to Build On
1. **Filter structure is well-defined** — `ExecutionFilter` in `history_query.py` with typed conditions
2. **URL synchronization works** — `Filters.toSearch()` / `fromSearch()` round-trip
3. **Component separation** — `FilterBar` (UI) + `Filters` (value) + `ExecutionFilter` (backend conditions)
4. **Reusable selection/bulk** — `Selection` + `BulkBar` already generic
5. **Operator variety exists** — `IN` (status, origin), `LIKE` (pipeline, q), range (since/until), equality (pipeline ID)

#### ⚠️ Gaps for Generic Query Builder

| Gap | Current State | Effort to Implement |
|-----|---------------|---------------------|
| Field registry | Hardcoded in `FilterBar` + `ExecutionFilter` | Medium — extract field definitions to shared config |
| Operator registry | Hardcoded per field in `ExecutionFilter.conditions()` | Medium — define operators per field type (text, enum, datetime, number) |
| Visual builder UI | None | High — new component: condition rows, group (AND/OR), field picker, operator picker |
| Expression parser | None | High — parse text to AST, validate against field registry, compile to SQLAlchemy |
| Reusability across domains | Executions-only | Medium — abstract `FilterBar` → `QueryBuilder` with pluggable field registry |

#### 🔧 Recommended Approach (Phased, Minimal Invasion)

**Phase 1: Field & Operator Registry (Foundation)**
```python
# engine/query_builder.py (new)
class FieldDef:
    name: str
    label: str
    type: Literal["enum", "text", "datetime", "number", "boolean"]
    operators: list[OperatorDef]  # e.g., enum: ["in", "not_in"]; text: ["contains", "not_contains", "is", "is_not"]
    enum_values: list[str] | None  # for enum type
    # ... validation, transformation to SQLAlchemy

FIELD_REGISTRY_EXECUTIONS = [
    FieldDef(name="status", label="Status", type="enum", operators=["in", "not_in"], enum_values=RunStatus.values()),
    FieldDef(name="started_by", label="Started by", type="enum", operators=["in", "not_in"], enum_values=StartedBy.values()),
    FieldDef(name="pipeline", label="Pipeline", type="text", operators=["contains", "not_contains", "is", "is_not"]),
    FieldDef(name="q", label="Search", type="text", operators=["contains", "not_contains"]),
    FieldDef(name="started_at", label="Started", type="datetime", operators=["before", "after", "between", "in_last"]),
    # ...
]
```

**Phase 2: Backend Query Compiler**
- `QueryCompiler.compile(filter_ast: FilterNode) -> list[ColumnElement[bool]]`
- `FilterNode` = `AndNode(children)` | `OrNode(children)` | `ConditionNode(field, operator, value)`
- Reuse `_contains`, `_choice`, `_time` from `history_query.py`

**Phase 3: Visual Mode UI Component**
- New `QueryBuilder` component (replaces `FilterBar`)
- Renders as: field picker → operator picker → value input (per operator)
- Groups: "Add condition", "Add group (AND/OR)"
- Outputs `FilterNode` AST; serializes to URL (extend `Filters.toSearch()`)

**Phase 4: Advanced Expression Editor**
- Textarea with Monaco/CodeMirror-lite or custom highlighter
- Grammar: `field operator value` (e.g., `status in (done, failed) AND started_at after 2026-01-01`)
- Parser → AST → same compiler as Visual Mode
- Bidirectional sync: Visual ↔ Expression

**Phase 5: Integration Points**
- Global executions page: swap `FilterBar` → `QueryBuilder` (same `Filters` value object initially)
- History tab: add "Advanced filters" toggle
- Future: board, agents, secrets — each defines its `FIELD_REGISTRY`

#### 🎯 Key Design Decisions

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| **AST format** | JSON-serializable plain objects | URL-safe, debuggable, language-agnostic |
| **Operator semantics** | Backend-owned (compile to SQLAlchemy) | Security: no raw SQL; single source of truth |
| **Visual ↔ Expression sync** | Bidirectional, Expression is source of truth | Power users edit text; Visual is projection |
| **Grouping** | Explicit AND/OR groups (not implicit precedence) | Simpler UI, matches SQL WHERE logic |
| **Reusability** | Component accepts `fieldRegistry` prop | Each domain provides its registry; component is generic |

---

### 4.3 Cross-Cutting Concerns

#### 4.3.1 Data Model Impact
- **Retention extensions**: No schema changes needed. Settings table may need `execution_history_default_keep` column (or reuse existing `Settings` key-value if one exists).
- **Query builder**: No schema changes. Pure application logic.

#### 4.3.2 API Surface
| New Endpoint | Purpose | Breaking? |
|--------------|---------|-----------|
| `GET /api/settings/execution-history-default` | Read global default | No |
| `PUT /api/settings/execution-history-default` | Write global default | No |
| `GET /api/retention/templates` | List policy templates | No |
| `POST /api/tasks/bulk/history-policy` | Apply policy to multiple artifacts | No |
| `POST /api/tasks/{id}/history-policy/preview` | Preview deletion count | No |
| `GET /api/query/fields?domain=executions` | Field registry for query builder | No |
| `POST /api/query/validate` | Validate expression AST | No |

#### 4.3.3 Frontend Architecture
- **New component**: `QueryBuilder` in `static/js/components/query-builder.js`
- **Shared types**: `FilterNode`, `FieldDef`, `OperatorDef` in `static/js/query/`
- **Migration path**: `FilterBar` → `QueryBuilder` behind feature flag; `Filters` value object stays compatible

#### 4.3.4 Testing Strategy
- **Retention**: Extend existing truth-table tests; add preview/bulk tests
- **Query builder**: Unit test compiler with fixture registries; E2E test visual mode + expression sync
- **Regression**: Existing `test_history.py`, `test_executions.py` must pass unchanged

---

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Query builder scope creep | High | Medium | Strict phase gates; ship Visual Mode first, Expression Editor later |
| Expression parser complexity | Medium | High | Start with restricted grammar (no parentheses, flat AND); extend incrementally |
| Performance of dynamic SQL | Low | Medium | Keyset paging + indexes unchanged; compiler produces same `WHERE` clauses as hand-written |
| Breaking existing filter URLs | Low | High | `Filters.toSearch()`/`fromSearch()` unchanged; new params additive only |
| Retention bulk apply on large artifacts | Low | Medium | Chunked (500 IDs), same as bulk delete; transaction per artifact |
| Policy template conflicts with artifact policy | Low | Low | Templates only pre-fill; user must save explicitly |

---

## 6. Implementation Sequence Recommendation

### Retention Management (Week 1–2)
1. **Settings endpoint** for global default (`/api/settings/execution-history-default`)
2. **Policy templates** constant + `GET /api/retention/templates`
3. **Preview endpoint** (`POST /history-policy/preview`)
4. **Bulk apply endpoint** (`POST /api/tasks/bulk/history-policy`)
5. **UI**: Settings page section; template dropdown in `RetentionEditor`; "Apply to selected" in executions bulk bar

### Query Builder (Week 3–6)
1. **Field/Operator registry** (Python + TypeScript shared definitions)
2. **Query compiler** (Python: AST → SQLAlchemy conditions)
3. **Visual Mode component** (condition rows, groups, field/operator pickers)
4. **Expression parser** (text → AST, validation against registry)
5. **Expression Editor component** (textarea + highlighter + error annotations)
6. **Bidirectional sync** (Visual ↔ Expression)
7. **Integration**: Replace `FilterBar` on executions page; add to history tab

---

## 7. Conformance with Binding Prioritization

| Priority | This Audit's Alignment |
|----------|------------------------|
| 1. Repository evidence & ADRs | All recommendations reference existing ADR-025, ADR-028, models, components |
| 2. Existing implementation & patterns | Reuses `ExecutionHistory.prune()`, `ExecutionFilter`, `Selection`, `BulkBar`, `Filters` |
| 3. Defined UI/UX concepts | Extends `RetentionEditor`, `FilterBar` patterns; follows existing modal/confirm/alert patterns |
| 4. New requirements | Addressed as minimal extensions, not rewrites |
| 5. Own recommendations | Clearly separated in "Recommended Approach" sections |

---

## 8. Conclusion

The codebase provides **strong foundations** for both extensions:

- **Retention Management**: 90% implemented; needs only UI wiring for global default, templates, preview, and bulk apply. **No migrations, no new tables, low risk.**
- **Query Builder**: Core filter logic exists but is executions-specific. A **phased extraction** of field/operator registry + compiler + generic UI component will yield a reusable system. **Medium effort, high reuse value.**

Both features can be built **incrementally** without disrupting the existing Executions page or History tab. The component architecture (`Selection`, `BulkBar`, `Modal`, `ConfirmDialog`) is ready for reuse.

---

## Appendix: Key File References

| Area | Files |
|------|-------|
| Retention model | `models/runs.py:59–107` (Execution), `models/runs.py:21–57` (PipelineRun) |
| Retention logic | `engine/history.py:163–186` (prune), `engine/history.py:68–79` (policy) |
| Retention API | `api/tasks.py:203–219` (set_history_policy), `api/executions.py:66–76` (bulk delete) |
| Retention UI | `static/js/tasks/retention-editor.js`, `templates/components/history_panel.html` |
| Global executions | `engine/history_query.py`, `api/executions.py` |
| Executions UI | `static/js/executions/{page.js,filters.js,filter-bar.js,table.js}` |
| Reusable components | `static/js/components/{selection.js,bulk-bar.js,confirm-dialog.js,modal.js}` |
| Schemas | `engine/schemas.py` (HistoryPolicy, ExecutionsPage, ExecutionFilter) |
| Tests | `tests/test_history.py` (truth table), `tests/e2e/test_executions.py` (E2E) |
| ADRs | `docs/architecture/adr/025-execution-history-and-retention.md`, `docs/architecture/adr/028-global-executions-page-and-keyset-paging.md` |
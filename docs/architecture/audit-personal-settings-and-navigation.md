# Architecture & UX Audit: Personal Settings & Modular Navigation

**Date:** 2026-11-25  
**Status:** Audit only — no implementation, no code changes

---

## 1. Executive Summary

This audit examines two foundational extensions for the Settings area and the navigation system:

1. **Personal Settings** — a new "Personal" section under Settings where the single user of the application manages personal preferences. The first setting ("Mark resolved references") serves as proof-of-concept: it controls whether `${card.X}` references in artifact titles/bodies are visually highlighted in the artifact dialog and on board cards, with a legend. Default: off.

2. **Modular Navigation** — the owner requires that navigation and sub-navigation be modular, built on an abstract base class from which entries inherit and specialize (label, icon, target, children). A single central registration point; one change for all entries; new entries in few lines.

**Key finding:** The codebase already has strong foundations for both:
- `AppSetting` model (`models/settings.py`) stores key-value settings at runtime
- Settings API (`api/settings.py`) provides `/api/settings/*` and `/api/v1/settings/*` with `settings.changed` events
- `Navigation` classes (`web/navigation.py`) with `NavLink`, `NavGroup`, `NavField`, `NavAction`, `NavDivider` and `nav.html` template component
- Form manifest system (`ui/forms/*.yaml`, ADR-062) for declarative configuration windows
- i18n system with `nav.<key>.label/.tooltip` keys already in use

**Recommendation:** Build Personal Settings as a form manifest (`ui/forms/personal.yaml`) served by the existing `form-view.js` component, backed by a new `/api/settings/personal` endpoint using the `AppSetting` table with namespaced keys (`personal.mark_resolved_references`). For navigation, formalize the existing class hierarchy with an abstract `NavEntry` base, add a central `NavigationRegistry`, and migrate existing hardcoded entries incrementally.

---

## 2. Existing Architecture Evidence

### 2.1 Settings Storage & API (Personal Settings Foundation)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Runtime settings table** | `AppSetting(key PK, value JSON text, updated_at)` — one row per key | `models/settings.py:13-25` |
| **Settings API (browser)** | `build_settings_router("/api", ["settings"])` → `GET/PUT /api/settings/run-limits`, `GET/PUT/POST /api/settings/retention*` | `api/settings.py:38-148` |
| **Settings API (integration)** | `build_settings_router("/api/v1", ["integration API"], [Depends(require_api_token)])` — same endpoints under `/api/v1` | `api/settings.py:250-255` |
| **Event publication** | `request.app.state.event_bus.publish("settings.changed", {...})` after successful write | `api/settings.py:83-85, 128-130` |
| **UI: Run limits page** | `run_limits.html` + `run-limits-page.js` — two number fields, save on submit, live sync via SSE | `templates/run_limits.html`, `static/js/settings/run-limits-page.js` |
| **UI: Providers/Credentials** | Modal forms with own Save button — outside persist-on-change rule (catalog rule 5 exception) | `templates/providers.html`, `templates/credentials.html` |

### 2.2 Navigation System (Current State)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Base classes** | `NavItem` (key, label, icon, title), `NavLink` (href, children), `NavGroup` (runtime children), `NavField`, `NavAction`, `NavDivider` | `web/navigation.py:14-77` |
| **Navigation container** | `Navigation(name, groups: dict[str, list[NavItem\|NavDivider]])` with `.add(item, group)` | `web/navigation.py:79-89` |
| **Sidebar definition** | `SIDEBAR` constant — `Navigation("sidebar")` with `NavLink` entries (Board, Pipeline→children, Executions, Settings→children) | `web/navigation.py:93-123` |
| **Artifact rail definition** | `ARTIFACT_RAIL` constant — fields, dividers, group, actions | `web/navigation.py:125-140` |
| **Template component** | `nav.html` macros: `nav_link`, `nav_item` (switches on `kind`), `nav_items` | `templates/components/nav.html:1-58` |
| **i18n keys** | `nav.<key>.label`, `nav.<key>.tooltip`, `nav.<key>.value` — used in template via `t('nav.' ~ item.key ~ '.label')` | `templates/components/nav.html:5-9, 27-30` |
| **Client-side groups** | `nav-group.js` — fills `NavGroup` children at runtime (artifact fields rail) | `static/js/components/nav-group.js` |
| **Registration in app** | `templates.env.globals["navigation"] = navigation` in `web/routes.py:55` | `web/routes.py:55` |

### 2.3 Form Manifest System (ADR-062) — For Personal Settings UI

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Manifest location** | `ui/forms/*.yaml` (e.g., `guard.yaml`) | `ui/forms/guard.yaml` |
| **Schema** | `FormManifest` with `sections[]` → `fields[]` with `widget: switch|text|number|select|...`, `visible_when`, `advanced` | `ui/forms.py:63-174` |
| **Built-in widgets** | `text`, `number`, `textarea`, `select`, `choice`, `chips`, `switch`, `readonly` | `ui/forms.py:30-39` |
| **Browser renderer** | `form-view.js` — draws form from manifest, two-column grid, tooltips, advanced folded, per-field errors | `static/js/components/form-view.js` |
| **Localization** | `localize(description, language)` overlays `forms.<form>.sections.<key>.title`, `fields.<key>.label/help/placeholder` | `ui/forms.py:212-240` |
| **API endpoint** | `GET /api/forms/{name}` returns localized manifest (`api/forms.py`) | `api/forms.py` |

### 2.4 Card References Resolution (ADR-064) — For Example Setting

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Resolution function** | `resolve_body(body, card, max_words)` — fills `${card.title}`, `${card.number}`, `${card.id}`, `${card.<field>}` | `artifact_fields/body.py:115-128` |
| **API response** | `GET /api/tasks/{id}` returns `body` (original), `body_resolved` (filled or `null`), `preview` (first 60 words filled) | `tasks/service.py:144-167, 169-176` |
| **Board preview** | `cardPreview(task)` → `task.preview` else `task.body`; client cuts original if no `preview` | `static/js/tasks/body-model.js:17-19` |
| **Artifact dialog view** | `renderReferences(bodyText(task), findByNumber)` — `bodyText` returns `body_resolved` or original | `static/js/tasks/artifact-dialog.js:254, 11-14` |
| **Owner decision** | No "References resolved" marker, no "Show as written" toggle — Edit shows original; resolved text shown directly | ADR-064 §2, last bullet; `artifact-dialog.js:249-258` |

### 2.5 UI Catalog & Persistence Rules

| Rule | Description | Reference |
|------|-------------|-----------|
| **Catalog components** | Every control from catalog: `ge-switch`, `button`, `field`, etc. — no custom CSS | `docs/guides/ui-catalog.md:14-17, 43-44` |
| **Persist on user act** | Switch saves on change; text on focusout/Enter; no autosave, no debounce | `docs/guides/ui-catalog.md:25-39` |
| **Window sizing** | As wide as necessary, as narrow as possible; two-column grid where room allows | `docs/guides/ui-catalog.md:18-20, 156-173` |
| **Tokens only** | Colours from `static/css/tokens.css` (`var(--color-*)`); no literals | `docs/guides/ui-catalog.md:45-49` |
| **Dark mode** | Both themes define same tokens; component works in both | `docs/guides/ui-catalog.md:46-47` |

---

## 3. Audit Findings

### 3.1 Part A: Personal Settings

#### 3.1.1 Data Model & Storage

**Current state:** `AppSetting` table stores arbitrary key-value pairs as JSON text. Keys use dotted names such as `run.max_steps` (`models/settings.py`); the new ones follow that style (`personal.mark_resolved_references`). No personal settings yet.

**Gap to requirement:** Need namespaced keys (`personal.*`) to separate personal from global/admin settings later (per card #99: System → Global → Personal resolution).

**Recommendation:** Use `AppSetting` with keys `personal.mark_resolved_references` (boolean), `personal.<future_setting>`. Value stored as JSON (`"true"`, `"false"`, `"auto"`, etc.). No schema migration needed — table accepts any key.

**Validation:** At API layer (Pydantic model), not database. Default values defined in manifest (see 3.1.2).

#### 3.1.2 Central Declaration (Manifest)

**Requirement:** Every setting declared once in a manifest (key, type, default, label/help in all languages, group). Page drawn from manifest; new setting = manifest entry only.

**Current parallel:** Node manifests (`graph/nodes/*.yaml`) and form manifests (`ui/forms/*.yaml`, ADR-062) follow this pattern.

**Recommendation:** Create `ui/forms/personal.yaml` as a form manifest:

```yaml
schema: 1
name: personal
columns: 2
width: 50
sections:
  - key: display
    title: Display
    column: 1
    fields:
      - key: mark_resolved_references
        widget: switch
        label: Mark resolved references
        help: Highlight ${card.X} references in artifact dialog and board cards with a coloured background and show a legend.
        default: false
```

**Why form manifest over new format:** Reuses `form-view.js`, `form-widgets.js` (has `switch`), i18n overlay, validation, two-column layout, advanced folding. No new component needed.

**i18n keys needed:**
- `forms.personal.sections.display.title` → "Display" / "Anzeige"
- `forms.personal.fields.mark_resolved_references.label` → "Mark resolved references" / "Aufgelöste Referenzen markieren"
- `forms.personal.fields.mark_resolved_references.help` → (as above)

#### 3.1.3 API: Read & Write

**Current pattern:** `GET/PUT /api/settings/run-limits` → `RunLimitsRead/Write` Pydantic models → `load_limits`/`save_limits` in `engine/limits.py`.

**Recommendation:** Add `GET/PUT /api/settings/personal` under same router:

```python
# api/settings.py additions
class PersonalSettingsRead(BaseModel):
    mark_resolved_references: bool = False
    # future fields here

class PersonalSettingsWrite(BaseModel):
    mark_resolved_references: bool | None = None
    # future fields here

@router.get("/personal", response_model=PersonalSettingsRead)
async def get_personal(session: SessionDep) -> PersonalSettingsRead:
    # read from AppSetting where key LIKE 'personal.%'
    ...

@router.put("/personal", response_model=PersonalSettingsRead)
async def put_personal(payload: PersonalSettingsWrite, request: Request, session: SessionDep):
    # write changed keys to AppSetting
    await session.commit()
    request.app.state.event_bus.publish("settings.changed", {"personal": result.model_dump()})
    return result
```

**Error behavior:** 422 for invalid boolean; 401/403 via existing `GATED` dependencies; unknown keys ignored (forward-compatible).

**Permissions:** Today single user → no auth check beyond existing API token/OIDC. Designed for later: `personal.*` keys scoped to user when multi-user arrives (card #99).

#### 3.1.4 UI: Page from Catalog Components

**Structure:** Settings page (`/settings/personal`) extends `base.html`, includes `form-view.js`, loads manifest via `GET /api/forms/personal`, renders in a `st-card glass` container (like `run_limits.html`).

**Components used:**
- `ge-switch` for boolean (catalog: `switch.js`, `forms.css:.ge-switch`)
- Section titles, help tooltips via `info-tip.js` (catalog)
- Two-column grid (form manifest `columns: 2`), stacks on narrow (catalog rule 2)
- Save: switch persists on change (catalog rule 5) — no Save button needed for pure-switch page; if mixed, add Save button per rule 6

**Accessibility:** `ge-switch` uses `role="switch"`, `aria-checked`, `aria-labelledby`; focus ring via global tokens; labels via `<label for="...">`.

**Dark mode:** Only colour tokens (`--color-accent`, `--btn-outline-border`, etc.) — works automatically.

**Texts:** All from i18n (English source in manifest, German in `de.json` via `forms.personal.*` keys).

#### 3.1.5 Browser Value Delivery

**On page load:** Page fetches `GET /api/settings/personal` → populates form via `form-view.js` `load(values)`.

**On change:** `ge-switch` fires `change` event → `form-view.js` calls `persist` → `PUT /api/settings/personal` with changed key → SSE `settings.changed` broadcasts to other tabs → other tabs call `show(data.personal)` if not dirty.

**Language/Theme:** Currently cookie/browser (`oa_lang` cookie, `theme` cookie). **Decision needed:** Should they move under Personal Settings? Recommendation: **Not in this step** — keep as cookies; document as future migration candidate in manifest (visible_when or separate section).

#### 3.1.6 Example Setting: Mark Resolved References — Full Trace

| Layer | Current | With Setting ON |
|-------|---------|-----------------|
| **Server resolution** | `artifact_fields/body.py:resolve_body()` returns single string `body_resolved` | Unchanged — server still returns resolved text |
| **API response** | `body_resolved: string|null`, `body: string` (original) | Unchanged — same response shape |
| **Client: artifact dialog** | `bodyText(task)` returns `body_resolved || body`; rendered via `renderReferences()` | **New:** Split into segments — original text vs. substituted spans |
| **Client: board card** | `cardPreview(task)` returns `preview` (first 60 words resolved) | **New:** Same segmented rendering for preview |
| **Visual marking** | None | **New:** Wrap substituted segments in `<mark class="resolved-ref">` with CSS `background: var(--color-resolved-ref-bg)` |
| **Legend** | None | **New:** Small footer in dialog / tooltip on card: `▉ Resolved reference` |

**Required server change:** `resolve_body` must return **segments** instead of flat string:
```python
# New return type: list[Segment] where Segment = {text: str, resolved: bool}
def resolve_body_segments(body: str, card: Mapping) -> list[Segment]:
    # returns e.g. [{"text": "Ticket ", "resolved": False}, {"text": "123", "resolved": True}, ...]
```

**Client rendering:** `renderReferences` → `renderResolvedBody(segments)` producing:
```html
<span data-resolved-body>
  Ticket <mark class="resolved-ref">123</mark> — <mark class="resolved-ref">Fix login</mark>
</span>
<details class="resolved-legend" hidden><summary>Legend</summary>▉ Resolved reference</details>
```

**Token for highlight:** Add `--color-resolved-ref-bg` to `tokens.css` (light: `var(--color-accent)` at 15% opacity; dark: `var(--color-accent)` at 25%) — meets 3:1 contrast against card background per catalog.

**Search/Preview impact:** Search indexes original `body` (unchanged). Preview shows first 60 words with marks — same budget logic, just richer markup.

#### 3.1.7 Tests

| Test Type | What It Secures | Priority |
|-----------|-----------------|----------|
| **Unit (Python)** | `resolve_body_segments` correctness: boundaries, empty fields, self-references, nested, malformed | High |
| **Unit (Python)** | `PersonalSettingsRead/Write` validation, default values, unknown key handling | High |
| **API** | `GET/PUT /api/settings/personal` round-trip, SSE `settings.changed` payload, 422 on invalid | High |
| **API** | `GET /api/forms/personal` returns localized manifest with i18n overlays | Medium |
| **Browser (E2E)** | Personal page loads, switch toggles, value persists across reload, other tab syncs via SSE | High |
| **Browser (E2E)** | Artifact dialog shows resolved highlights when ON; no highlights when OFF; legend appears | High |
| **Browser (E2E)** | Board card preview shows highlights when ON; no highlights when OFF | Medium |
| **Visual regression** | Highlight token contrast in light/dark (catalog test matrix) | Medium |

#### 3.1.8 Risks, Open Questions, Alternatives

| Risk / Question | Assessment | Recommendation |
|-----------------|------------|----------------|
| **Segmented resolution API change** | Breaks `body_resolved` string contract | Add `body_resolved_segments` alongside; keep `body_resolved` for compat; clients opt in |
| **Performance on large bodies** | Token-by-token walk already budgeted; segments add array allocation | Acceptable — budget stops early; segments only for bodies with references |
| **Where legend lives** | Dialog: footer; Board card: tooltip or popover | Dialog: collapsible `<details>` in view mode; Board: hover tooltip on first mark |
| **Language/Theme migration** | Not in scope; keep cookies for now | Document in manifest as `visible_when: {field: _meta.migration, equals: true}` placeholder |
| **Multi-user scoping (card #99)** | `AppSetting` has no user_id | Add `user_id` column later (nullable, default NULL = global); personal keys written with current user_id |

**Owner decisions needed:**
1. **D1:** Segmented response (`body_resolved_segments`) vs. client-side re-parse (recommend: server segments — single source of truth)
2. **D2:** Legend in dialog — always visible, collapsible, or only on hover? (recommend: collapsible `<details>` default closed)
3. **D3:** Board card — highlight in preview only, or full body on hover? (recommend: preview only; full body in dialog)
4. **D4:** Token name — `--color-resolved-ref-bg` or `--color-mark-resolved-bg`? (recommend: `--color-resolved-ref-bg`)

---

### 3.2 Part B: Modular Navigation

#### 3.2.1 Inventory: What Exists vs. Requirement

| Requirement (Owner) | Current State | Gap | Evidence |
|---------------------|---------------|-----|----------|
| **Abstract base class** | `NavItem` (dataclass) — has key, label, icon, title, `kind` | ✅ Exists but not abstract; no shared interface for `visible_when`, `order`, `badge` | `web/navigation.py:14-28` |
| **Specializations inherit** | `NavLink`, `NavGroup`, `NavField`, `NavAction`, `NavDivider` extend `NavItem` | ✅ Done via dataclass inheritance | `web/navigation.py:30-77` |
| **Single central registration** | Two module-level constants: `SIDEBAR`, `ARTIFACT_RAIL` | ❌ Hardcoded constants; no registry; third party cannot add without editing this file | `web/navigation.py:93-140` |
| **Display text from i18n** | `nav.<key>.label/.tooltip` via template `t('nav.' ~ item.key ~ '.label')` | ✅ Works for sidebar/rail entries | `templates/components/nav.html:5-9, 27-30` |
| **Sub-entries: static children** | `NavLink.children: tuple[NavLink, ...]` — fixed at definition | ⚠️ Static only; no dynamic `visible_when` | `web/navigation.py:34-35` |
| **Sub-entries: runtime groups** | `NavGroup` — page fills via `nav-group.js` (artifact fields) | ✅ Exists for one use case only | `web/navigation.py:43-48`, `static/js/components/nav-group.js` |
| **Visibility/rights** | Not implemented | ❌ No `visible_when`/`permission` on entries | — |
| **Active state** | Template checks `item.key == active_nav` and `item.contains(active_nav)` | ✅ Works for `NavLink` | `templates/components/nav.html:6, 14` |
| **Hardcoded navigation outside system** | Settings pages: routes in `web/routes.py` (`/settings/providers`, `/settings/credentials`, `/settings/run-limits`) — not in `SIDEBAR` children until manually added | ❌ Settings sub-navigation duplicated: once in `SIDEBAR` constant, once in route definitions | `web/routes.py:198-213`, `web/navigation.py:116-120` |
| **Settings pages navigation** | Each settings page standalone; no sub-nav component | ❌ No reusable settings sub-nav | `templates/providers.html`, `run_limits.html` |

#### 3.2.2 Gap Analysis & Target Architecture

**Current:** Two global constants (`SIDEBAR`, `ARTIFACT_RAIL`) built at import time. Adding an entry = edit `navigation.py`. Third party = impossible without fork.

**Target:** 
- `NavigationRegistry` — single instance, populated at startup + by extensions
- `NavEntry` (abstract base) → `NavLink`, `NavGroup`, `NavAction`, `NavDivider`, `NavField`
- Each entry declares: `key`, `label_key` (i18n), `icon`, `order`, `visible_when` (a Python callable, see D7), `permission` (future), `children` (for groups/links), `badge` (optional)
- Registration: `registry.register(NavLink(...), parent="settings", order=10)`
- Rendering: `registry.build_sidebar(active_nav, context)` → list of entries filtered by `visible_when(context)`

**"Personal" under Settings in few lines:**
```python
# In a personal_settings module (auto-discovered or explicitly imported)
from openartifact.web.navigation import registry, NavLink

registry.register(
    NavLink(key="personal", label_key="nav.personal.label", icon="user", href="/settings/personal"),
    parent="settings",
    order=30,  # after run-limits (20)
)
```

**Third-party community add-on:**
```python
# In their package's __init__.py or entrypoint
from openartifact.web.navigation import registry, NavLink

registry.register(
    NavLink(key="myfeature", label_key="nav.myfeature.label", icon="star", href="/myfeature"),
    parent="sidebar",
    order=900,
)
```

#### 3.2.3 Mandatory Documentation & Enforcement

**Where to bind:**
1. **ADR** — New ADR (e.g., ADR-066) "Modular Navigation System" documenting base class, registry, registration API, visibility, ordering.
2. **`docs/guides/ui-catalog.md`** — Add navigation as a catalog component (like `ge-switch`, `form-view`); binding rules §1–5 apply.
3. **`docs/guides/extending.md`** — Document how a third party adds a nav entry (registration pattern).
4. **`.github/CONTRIBUTING.md`** — Add checklist item: "Navigation entries go through `NavigationRegistry`; no hardcoded links in templates/routes."

**Automated enforcement (test):**
```python
# tests/test_navigation_modularity.py
def test_no_hardcoded_nav_links_in_templates():
    """Scan templates for <a href="/settings/..."> or <a href="/pipelines"> outside nav.html macro."""
    forbidden = [
        r'href="/settings/',
        r'href="/pipelines"',
        r'href="/actions"',
        r'href="/agents"',
        r'href="/executions"',
    ]
    # ... walk templates, fail on matches outside components/nav.html
```

```python
# tests/test_navigation_registry.py
def test_all_routes_have_nav_entries():
    """Every GET route under / that returns HTML has a NavLink in registry."""
    # Collect routes from app.router.routes, filter HTML responses, check registry.keys()
```

Run in CI; fails if new page added without nav registration.

#### 3.2.4 Migration Path (Small Steps, No Visual Change)

| Step | Action | Tests |
|------|--------|-------|
| **1. Abstract base** | Convert `NavItem` to `ABC` with abstract `render(context)`; keep dataclass fields | Unit: subclasses instantiate, `kind` correct |
| **2. Registry class** | `NavigationRegistry` with `register()`, `build_sidebar()`, `build_rail()`; move `SIDEBAR`/`ARTIFACT_RAIL` construction into `registry.populate_builtin()` | Unit: registry builds same structure as old constants |
| **3. Visibility predicate** | Add `visible_when: Callable[[dict], bool] | None` to `NavEntry`; evaluate in `build_*` with an explicit context dict (the request's page and the feature flags; no user or rights while the system has one user, card #99) | Unit: entry hidden when predicate false |
| **4. Settings sub-nav** | Create `NavGroup("settings", "Settings", "settings")` with dynamic children from registry (filter `parent="settings"`); replace hardcoded children in `SIDEBAR` | E2E: Settings dropdown shows Providers, Credentials, Run limits, Personal |
| **5. Migrate routes** | In `web/routes.py`, remove hardcoded `_page(..., nav="providers")` — derive `active_nav` from registry via request path | E2E: Active highlight works on all settings pages |
| **7. Third-party API** | Document `registry.register()` in `extending.md`; add example plugin | Integration test: external package adds entry |
| **8. Enforcement test** | Add `test_no_hardcoded_nav_links_in_templates.py` and `test_all_routes_have_nav_entries.py` to CI | CI passes on current codebase |

---

## 4. Implementation Sequence

### Part A: Personal Settings

| Step | Description | Effort | Tests |
|------|-------------|--------|-------|
| **A1** | Add `PersonalSettingsRead/Write` models + `GET/PUT /api/settings/personal` in `api/settings.py` | Small | API unit, API E2E |
| **A2** | Create `ui/forms/personal.yaml` manifest with `mark_resolved_references` switch | Small | Form manifest validation, i18n check |
| **A3** | Add `/settings/personal` route + template (`personal.html`) loading form via `form-view.js` | Small | Browser E2E: load, toggle, persist, SSE sync |
| **A4** | Implement `resolve_body_segments` in `artifact_fields/body.py` (return segments) | Medium | Unit: segments correctness |
| **A5** | Extend API: add `body_resolved_segments` to `TaskRead` (optional, behind feature flag) | Small | API unit |
| **A6** | Update `artifact-dialog.js` view mode: render segments with `<mark class="resolved-ref">` + legend | Medium | Browser E2E: highlights on/off, legend |
| **A7** | Update `board.js` preview: render segments for preview when setting ON | Medium | Browser E2E: board card highlights |
| **A8** | Add `--color-resolved-ref-bg` token to `tokens.css` (light/dark, contrast verified) | Small | Visual regression, catalog test |
| **A9** | Add German translations for `forms.personal.*` and `nav.personal.*` keys | Small | i18n check (`tools/check_i18n.py`) |

### Part B: Modular Navigation

| Step | Description | Effort | Tests |
|------|-------------|--------|-------|
| **B1** | Create `NavigationRegistry` class + `NavEntry` ABC in `web/navigation.py` | Medium | Unit: registry builds current sidebar/rail |
| **B2** | Migrate `SIDEBAR`/`ARTIFACT_RAIL` to `registry.populate_builtin()` | Small | Unit: same output; E2E: navigation unchanged |
| **B3** | Add `visible_when` predicate support + context (page, features) | Medium | Unit: visibility toggles |
| **B4** | Replace Settings hardcoded children with dynamic `NavGroup("settings")` from registry | Small | E2E: Settings dropdown works |
| **B5** | Derive `active_nav` from registry in `web/routes.py` (remove manual `active_nav` args) | Small | E2E: Active highlight on all pages |
| **B6** | Add enforcement tests: `test_no_hardcoded_nav_links_in_templates.py`, `test_all_routes_have_nav_entries.py` | Small | CI passes |
| **B7** | Document in ADR-066, `extending.md`, `CONTRIBUTING.md` | Small | Docs review |
| **B8** | (Future) third-party registration API | Medium | Integration test |

---

## 5. Owner Decisions Required

| # | Decision | Recommendation |
|---|----------|----------------|
| **D1** | Segmented response (`body_resolved_segments`) vs. client-side re-parse | **Server segments** — single source of truth, no re-parse drift |
| **D2** | Legend in artifact dialog: always visible / collapsible / hover-only | **Collapsible `<details>` default closed** — discoverable, unobtrusive |
| **D3** | Board card: highlight in preview only, or full body on hover | **Preview only** — full body in dialog is the place for detail |
| **D4** | Highlight token name | **`--color-resolved-ref-bg`** — semantic, matches `--color-accent` family |
| **D5** | Language/Theme move to Personal Settings now or later | **Later** — keep cookies; add manifest placeholder with `visible_when: false` |
| **D6** | Navigation registry: global singleton vs. per-request | **Global singleton** (populated at startup) — simpler, matches current constant pattern |
| **D7** | `visible_when` expression language: Python callable / string expr / feature flag key | **Python callable only** — testable, no expression language and no `eval` of strings (a corrected recommendation: the first draft proposed an `eval`-safe subset) |
| **D8** | Order property: integer (like current `menu.order`) or lexical key | **Integer `order`** — matches node manifests (`menu.order`), allows insertion between |

---

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Segmented resolution breaks existing clients** | Medium | High | Keep `body_resolved` string; add `body_resolved_segments` as optional; feature-flag client opt-in |
| **Highlight contrast fails in dark mode** | Low | Medium | Define token in both themes; catalog test `test_ui_catalog.py` matrix covers it |
| **Navigation registry becomes bottleneck** | Low | Medium | Simple dict-based registry; no locks (populated at startup); extensions register before app serves |
| **Third-party nav entries clash on keys** | Medium | Low | Namespace convention: `ext.<pkg>.<feature>`; registry warns on duplicate key |
| **`visible_when` callable captures request incorrectly** | Medium | Medium | Pass explicit `context` dict (page, features); no closure over request |
| **Form manifest for settings feels heavy for one switch** | Low | Low | Reuse pays off at 2+ settings; `form-view.js` already loaded on other settings pages |
| **SSE `settings.changed` not received in all tabs** | Low | Medium | Existing pattern for run-limits/retention works; same bus, same retry logic |
| **Board preview performance with segments** | Low | Low | Preview limited to 60 words; segments array small; budget already stops early |

---

## Appendix: Key File References

| Area | Files |
|------|-------|
| Settings storage | `models/settings.py:13-25` (`AppSetting`) |
| Settings API | `api/settings.py:38-148` (`build_settings_router`) |
| Navigation classes | `web/navigation.py:1-140` |
| Navigation template | `templates/components/nav.html:1-58` |
| Form manifest system | `ui/forms.py`, `ui/forms/guard.yaml`, `static/js/components/form-view.js` |
| Card resolution | `artifact_fields/body.py:115-128` (`resolve_body`), `tasks/service.py:144-176` |
| Artifact dialog | `static/js/tasks/artifact-dialog.js:249-258` (view mode), `static/js/tasks/references.js` |
| Board preview | `static/js/tasks/body-model.js:17-19` (`cardPreview`) |
| UI Catalog | `docs/guides/ui-catalog.md`, `static/css/forms.css:.ge-switch`, `static/js/components/switch.js` |
| i18n | `openartifact/i18n/__init__.py`, `openartifact/i18n/locales/en.json` (nav.* keys) |
| ADRs | ADR-062 (forms), ADR-064 (card references), ADR-059 (catalog), ADR-056 (i18n) |

---

## Link Verification

All internal references verified with `python tools/check_links.py` — no broken links.
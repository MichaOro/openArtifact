# ADR-054: Node kinds are declared as YAML manifests

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-014](014-building-blocks-and-extension-points.md) (a kind of node is a manifest, no longer a class), [ADR-022](022-node-settings-as-json-config.md) (where settings are declared), [ADR-053](053-canonical-node-configuration.md)  
**Implemented in:** `graph/nodes/*.yaml` (19 kinds, `_menu.yaml`, `_shared.yaml`), `graph/manifest.py` (schema, loader, `CLIENT_FUNCTIONS`), `graph/validators.py` (`VALIDATORS`), `graph/node_types.py` (`NodeType`, behaviours, `load`), `api/schemas.py` (`NodeTypeRead`); `static/js/editor/node-types.js` (views per behaviour), `caption.js`, `view-functions.js`, `add-menu.js`; tests `tests/test_node_manifests.py`, `tests/js/view-golden.test.mjs`, `tests/js/caption.test.mjs`  
**Affected chapters:** guide [extending](../../guides/extending.md), [05.03](../arc42/05-building-block-view/05.03-backend-components.md)

## 1. Context

A kind of node was a Python class (settings, ports, help texts, rules) and a JavaScript class (caption, size, icon, which
ports show). Adding a kind meant writing both. The owner plans third-party kinds and a community hub, so the foundation
has to be a declaration that does not need code, and the existing 19 kinds should be built on it from the start rather
than rebuilt later.

## 2. Decision

- **One manifest per kind** (`graph/nodes/<kind>.yaml`, `schema: 1`), validated by pydantic models (`graph/manifest.py`),
  which also give the JSON Schema authors validate against. A bad manifest stops the start with its file name.
- **It declares:** label, scopes, ports (with *when they are there* and how they are labelled), settings (all fields of
  `Setting`, ADR-053 included), the "+" menu place, and the card (`ui`: icon, size, caption template, port labels).
- **Code is named, never written there.** Rules are names of `graph/validators.py`; captions are templates
  (`{key|filter}`, `{@field}`, `{?cond:text}`) or one of a few named functions of the editor; the way a kind connects is one
  of eight `behaviour`s (`plain`, `flow`, `tool`, and the structural `stage`, `action`, `pipeline`, `output`, `switch`),
  each a small class on the server (`connect_error`) and in the editor (how it is drawn). The names a manifest may use are
  listed in `CLIENT_FUNCTIONS`; a test checks the editor has exactly those.
- **Short files:** `use:` takes a setting from `_shared.yaml`; `repeat: N` writes a block N times (the If's rows, the Switch's
  cases and ports); `_menu.yaml` orders the clusters of the menu and the kinds.
- **One description for the editor:** `GET /api/node-types` carries `behaviour`, `menu`, `ui` and per port `visible_when` /
  `label_from` in addition to what it carried. The editor has one view per behaviour; there is no class per kind and no
  list of menu clusters in the browser (`ADD_GROUPS` is gone).
- **No behaviour change:** every old key of the description is identical to before (checked against a recording), and the
  look and the connection rules of every kind are kept by a golden test (`tests/js/fixtures/views-golden.json`).
  `tests/fixtures/node-types.json` is the live description; the editor tests read it, a Python test keeps it current.
- **New dependency:** PyYAML (already installed with `uvicorn[standard]`, now declared).

## 3. Not decided here

- **Third-party loading is not enabled.** `node_types.load(directory)` reads any directory, but only the built-in one is
  loaded. A kind is a row of the `NodeKind` enum and of the `ck_graph_nodes_kind` constraint and needs an executor
  (`engine/executors.py`); a manifest of a third party therefore cannot add a working kind yet. The next step is a
  *template* executor (a kind that only presets another kind's settings, `extends: http`) and kinds as data instead of
  an enum; it needs its own ADR (trust, installation, versioning).
- Structural behaviours (stage, action, pipeline, output) are for the built-in kinds; community manifests would be
  limited to `plain`, `flow` and `tool`.

## 4. Consequences

A new kind of an existing behaviour is one YAML file, a `NodeKind` member, a migration for the constraint and an executor;
no editor code. The shared snippets and the golden test make a change of a common setting a one-line edit that every kind
shows. Help texts and defaults now live in YAML, reviewed like code but not type-checked by mypy: the schema and the
parity tests are what catch a typo.

## 5. Addendum 2026-11-25: the card, the colour and the result are data too

The views of the editor were data driven, but the CSS and a few lists were not: the card layout and colour existed as rules for
five kinds (`.ge-node--code, .ge-node--http, ...`), so the Artifact, GitHub, Postgres and Edit Fields nodes fell back to an older
look (their icon over the title), and `RESULT_KINDS = [code, http, timer, if, switch, agent, set]` in the reference suggestions
left the result of GitHub, Postgres and Artifact nodes out of every `${...}` field and out of the mapping of an agent's inputs.
That is a per-kind code path, which this ADR set out to remove.

- **The look is keyed by behaviour.** The canvas sets `data-behaviour` on every card and `--node-color` from the manifest's
  `ui.color` (`var(--node-<color>, var(--node-action))`); `editor.css` has one set of rules per behaviour (a flow card, a plain
  card, an output, a stage) and none per kind. New tokens `--node-github`, `--node-postgres`, `--node-set`, `--node-artifact`
  and `--node-mcp` are built from the lane hues. The caption of a card is the secondary text colour: the muted one fell under
  4.5:1 on the tinted cards of some kinds (the test measures every kind in both themes).
- **What a kind leaves is its own declaration.** `produces_result`, `result_data` (keys of `data` offered after `${(Name).data.`),
  `variables` (the setting that holds the run variables the node sets) and `timed` (the flow panel shows its duration) replace
  the lists in `reference-completion.js` and `flow-panel.js`. The editor asks the kind (`typeOf(kind)`), nothing else.
- **The step icon in the history** comes from the manifest (`ui.step_icon`, else `ui.icon`, else the menu glyph) as `icon` of every
  step the API returns, instead of a map in `history-step.js` that lacked three kinds.
- **Left as it is on purpose** (genuinely different behaviour, not "the same for every flow kind"): the structural rules of stage,
  action and pipeline connections and the tool-to-agent rule in `node-types.js`, which kind needs which credential setting
  (`credentials/store.py`), the executors, and the Agent's own settings block.

## Addendum (2026-11-26): `retry` and the result

`_shared.yaml` has the optional setting `retry` (setting type `retry`, stored in `config.retry`, checked by `retry_error`; the description carries its `limits`): [ADR-073](073-retry-on-fail.md). A kind that says `produces_result` must have an executor, and its result has the core of [ADR-072](072-result-contract.md); `tests/test_result_contract.py` keeps both.

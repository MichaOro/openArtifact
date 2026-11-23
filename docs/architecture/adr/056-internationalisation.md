# ADR-056: Internationalisation: English source, a dictionary per language

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-054](054-node-kinds-as-yaml-manifests.md) (texts of the manifests may be overridden per language)  
**Implemented in:** `openartifact/i18n/` (`__init__.py`: `t`, `plural`, `languages`, `language_of`; `web.py`: language of a request, template globals, the dictionary block; `locales/en.json`, `locales/de.json`), `graph/localize.py`, `api/graphs.py` (`GET /api/node-types`), `web/routes.py`, all templates, `static/js/i18n.js` and every script that shows text, `static/js/main.js` (the switcher), `tools/check_i18n.py`; tests `tests/test_i18n.py`, `tests/js/i18n.test.mjs`, `tests/e2e/test_i18n.py`  
**Affected chapters:** guide [languages](../../guides/i18n.md), [extending](../../guides/extending.md), [API reference](../../guides/api-reference.md); arc42 [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Context

Every text of the interface was written into templates and scripts. The owner wants other languages (German first, Italian
later) to be maintainable in one place, without a build step and without breaking the English text the tests rely on.

## 2. Decision

- **English is the source and the default.** One flat JSON dictionary per language (`locales/<code>.json`, dot-namespaced
  keys, `{name}` placeholders, `key.one` / `key.other` for plurals). The languages that exist are the files that exist.
- **Fallback chain** requested language, then English, then the key itself: a missing translation is never an error and a
  page is never empty. A language starts as a skeleton and grows.
- **The language of a request:** the cookie `oa_lang` (set by the switcher in the header), else `Accept-Language` (the first
  visit), else English. No user accounts: the choice is per browser. `<html lang>` follows it.
- **Server:** `t` / `plural` as Jinja globals (they read a context variable set just before a template renders, so macros
  imported without the context work too) and as Python functions for text the server writes.
- **Browser:** `static/js/i18n.js` with the same `t` / `plural` (`tn`). The page delivers the dictionary of its language laid
  over English as an inline **data block** (`<script type="application/json" id="i18n">`). A data block is not executed, so
  the strict CSP (`script-src 'self'`) needs no `unsafe-inline`; being in the page it needs no extra request and nothing
  flashes untranslated. Cost: the whole dictionary (about 60 KB) travels with every page.
- **Node manifests** stay the English source. A locale file may override texts by key (`nodes.<kind>.label`,
  `.settings.<key>.label|help|placeholder|options.<value>`, `.ports.<name>`, `.caption`, `nodes.menu.<cluster>`);
  `GET /api/node-types` applies them for the language of the request, the stored values (kinds, keys, options) never
  change. Option names are shown through `option_labels`.
- **Not translated, by design:** error messages of the API and MCP (part of the contract; the interface shows them as received),
  log messages, OpenAPI texts, user content.
- **Drift is a failing test:** `tools/check_i18n.py` (run by `tests/test_i18n.py`) finds keys used but undefined, defined but
  unused, keys a language has that English lacks, and placeholders that differ from English. Missing translations are only
  reported (`--all`).

## 3. Consequences

- Positive: a language is one file; English output is unchanged (every page was compared with the previous version, the
  existing suites pass); adding the second language needs no code.
- Negative: sentence pieces around markup in a few templates cannot reorder; the dictionary is sent with every page; keys of
  shared words (`common.`) may need a second key when another language needs a different word in a context.
- Not done: right-to-left layout, locale-aware number and date formats beyond the browser's own (`toLocaleString`), a
  per-user default (no accounts yet).

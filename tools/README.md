# tools

Development tooling, standard library only.

- `check_quarantine.py` — checks `quarantine.json` (unused code that waits 14 days before it is
  removed); run weekly by `.github/workflows/quarantine.yml`. The rule for contributors is in
  [CONTRIBUTING](../.github/CONTRIBUTING.md#unused-code-quarantine).

An entry's `usage` is a regular expression that matches calls, not the definition. The script reads
the tracked `.py`, `.js`, `.html`, `.css`, `.toml`, `.yml` and `.sh` files (`git ls-files`; a file walk
outside a git checkout). Test files count as usage unless the entry lists them in `ignore`, an optional
array of path globs (for example `"apps/backend/tests/*"`) that are not searched for that entry, so code
that only tests call can be quarantined. An entry whose `symbol` no longer occurs in its `file` is
reported as stale.

    python tools/check_quarantine.py [--today YYYY-MM-DD]

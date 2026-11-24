# tools

Development tooling, standard library only.

- `check_quarantine.py` — checks `quarantine.json` (unused code that waits 14 days before it is
  removed; an empty `entries` list passes); run weekly by `.github/workflows/quarantine.yml`. The rule for contributors is in
  [CONTRIBUTING](../.github/CONTRIBUTING.md#unused-code-quarantine).

- `check_links.py` — checks the relative links and `#anchors` of every tracked Markdown file (GitHub's
  heading slugs; code blocks and external URLs are skipped); run by the `static` job in
  `.github/workflows/ci.yml`. `python tools/check_links.py [files...]`.
- `smoke_container.sh IMAGE` — starts a built image the way `deploy/docker-compose.yml` runs it (read-only root,
  tmpfs `/tmp`, no capabilities, `no-new-privileges`, a throw-away token and key on a random local port), imports
  every module, waits for `/health` and expects 401 on `/api/tasks` without and 200 with the token. Run by the
  `docker` job in CI; needs only Docker and curl.
- `test_audit.sh [--fast] [DIR]` — runs every check and test section in turn (ruff, mypy, links, i18n, quarantine,
  JavaScript, Python under coverage, browser tests) and writes a report with start, end, duration and exit code per
  section, plus one log per section, to DIR (default: a new temporary directory; nothing goes into the repository).
  `--fast` runs the Python tests in parallel without coverage. Exit code 1 if any section failed.

An entry's `usage` is a regular expression that matches calls, not the definition. The script reads
the tracked `.py`, `.js`, `.html`, `.css`, `.toml`, `.yml` and `.sh` files (`git ls-files`; a file walk
outside a git checkout). Test files count as usage unless the entry lists them in `ignore`, an optional
array of path globs (for example `"tests/*"`) that are not searched for that entry, so code
that only tests call can be quarantined. An entry whose `symbol` no longer occurs in its `file` is
reported as stale.

    python tools/check_quarantine.py [--today YYYY-MM-DD]

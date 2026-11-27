#!/usr/bin/env bash
# Full test-suite audit: every section with start, end, duration, exit code and result line.
#   tools/test_audit.sh [--fast | --ci] [OUTPUT_DIR]
# The report is OUTPUT_DIR/audit.md, the full output of each section OUTPUT_DIR/NN-<section>.log.
# OUTPUT_DIR defaults to a new directory under $TMPDIR (or /tmp); nothing is written into the repository.
# Default: the Python tests run one after the other under coverage (about half an hour, measures the 95 % bar).
# --fast: the Python tests run in parallel (-n 4) without coverage (a few minutes).
# --ci: as the GitHub workflow runs them, to find locally what only the slow runner shows: Python tests and browser tests one
#   after the other (no -n), on two cores (taskset -c 0,1, like the 2 vCPU of the runner), the browser tests with
#   "--tracing retain-on-failure" (traces of failed tests in OUTPUT_DIR/traces, to open with `playwright show-trace`).
#   Takes longer than the default mode (about 45 minutes for Python and 20 for the browser). Not the same: the runner also has a
#   Postgres for the tests that need one (OA_TEST_POSTGRES_URL), set it to run them here too.
# Needs the development dependencies (ruff, mypy, pytest, pytest-xdist, coverage, playwright) and node.
# The exit code is 1 when any section failed.
set -u
cd "$(dirname "$0")/.."

FAST=0
CI=0
if [ "${1:-}" = "--fast" ]; then FAST=1; shift; fi
if [ "${1:-}" = "--ci" ]; then CI=1; shift; fi
TWO=""
if [ "$CI" = 1 ]; then
  command -v taskset > /dev/null 2>&1 && TWO="taskset -c 0,1 "  # two cores, like the runner (skipped where taskset is missing)
fi
OUT=${1:-$(mktemp -d "${TMPDIR:-/tmp}/openartifact-audit-XXXXXX")}
mkdir -p "$OUT"
REPORT="$OUT/audit.md"
export COVERAGE_FILE="$OUT/.coverage"
T0=$(date +%s)
FAILED=0
{
  echo "# Test audit"
  echo
  echo "- Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "- Commit: $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD), $(git status --short | wc -l) changed files in the working tree"
  echo "- Host: $(nproc) cores, mode: $([ $FAST = 1 ] && echo fast || { [ $CI = 1 ] && echo "ci (serial, ${TWO:+two cores, }traces)" || echo full; })"
  echo
  echo "| # | Section | Start | End | Duration | Exit | Result |"
  echo "|---|---|---|---|---|---|---|"
} > "$REPORT"

N=0
section() { # name, command
  local name=$1 cmd=$2
  N=$((N + 1))
  local log s e start end rc result
  log="$OUT/$(printf '%02d' "$N")-${name// /_}.log"
  s=$(date +%s); start=$(date '+%H:%M:%S')
  bash -c "$cmd" > "$log" 2>&1
  rc=$?
  e=$(date +%s); end=$(date '+%H:%M:%S')
  [ "$rc" -ne 0 ] && FAILED=1
  result=$(grep -E "passed|failed|error|All checks passed|Success|^ok|^ℹ (pass|fail)|broken|^TOTAL|already formatted" "$log" | tail -3 | tr '\n' ' ' | sed 's/|/\//g' | cut -c1-160)
  printf '| %d | %s | %s | %s | %ds | %d | %s |\n' "$N" "$name" "$start" "$end" "$((e - s))" "$rc" "$result" >> "$REPORT"
}

section "ruff lint"        "ruff check ."
section "ruff format"      "ruff format --check ."
section "mypy"             "mypy ."
section "check links"      "python3 tools/check_links.py"
section "check i18n"       "python3 tools/check_i18n.py"
section "check quarantine" "python3 tools/check_quarantine.py"
section "JS unit tests"    "node --test 'tests/js/*.test.mjs'"
if [ $FAST = 1 ]; then
  section "Python tests"   "python3 -m pytest -n 4 -p no:cacheprovider -q"
else
  section "Python tests with coverage" "${TWO}coverage run -m pytest -p no:cacheprovider $([ $CI = 1 ] && echo '-v --tb=short' || echo -q)"
  section "coverage report" "coverage report --skip-empty --sort=cover | head -40"
fi
if [ $CI = 1 ]; then
  section "E2E browser tests" "${TWO}python3 -m pytest -m e2e -p no:cacheprovider -v --tb=short --tracing retain-on-failure --output '$OUT/traces'"
else
  section "E2E browser tests" "python3 -m pytest -m e2e -n 3 -p no:cacheprovider -q"
fi

T1=$(date +%s)
{
  echo
  echo "- Finished: $(date '+%Y-%m-%d %H:%M:%S %Z'), total $(( (T1 - T0) / 60 )) min $(( (T1 - T0) % 60 )) s, $([ $FAILED = 0 ] && echo 'all sections passed' || echo 'AT LEAST ONE SECTION FAILED')"
} >> "$REPORT"
cat "$REPORT"
exit $FAILED

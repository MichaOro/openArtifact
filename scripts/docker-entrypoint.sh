#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# OpenArtifact Docker entrypoint
#
# 1. Run Alembic migrations to initialize or upgrade the database
# 2. Start the uvicorn server
#
# All configuration via OPENARTIFACT_ environment variables.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

export OPENARTIFACT_PORT="${OPENARTIFACT_PORT:-2909}"
export OPENARTIFACT_HOST="${OPENARTIFACT_HOST:-0.0.0.0}"
export OPENARTIFACT_LOG_LEVEL="${OPENARTIFACT_LOG_LEVEL:-INFO}"
export OPENARTIFACT_DATA_DIR="${OPENARTIFACT_DATA_DIR:-/data}"
export OPENARTIFACT_DATABASE_FILENAME="${OPENARTIFACT_DATABASE_FILENAME:-openartifact.db}"

# Uvicorn expects lowercase log level
LOG_LEVEL_LOWER="$(echo "${OPENARTIFACT_LOG_LEVEL}" | tr '[:upper:]' '[:lower:]')"

echo "=== OpenArtifact Docker Entrypoint ==="
echo "Port: ${OPENARTIFACT_PORT}"
echo "Host: ${OPENARTIFACT_HOST}"
echo "Log level: ${OPENARTIFACT_LOG_LEVEL}"
echo "Data directory: ${OPENARTIFACT_DATA_DIR}"
echo "Database file: ${OPENARTIFACT_DATABASE_FILENAME}"

# Make openartifact package importable from /app
export PYTHONPATH="/app:${PYTHONPATH:-}"

# ── Database migration ─────────────────────────────────────────────
echo ""
echo "--- Running database migrations ---"
cd /app

if alembic upgrade head; then
    echo "Migrations completed successfully."
else
    echo "ERROR: Database migration failed. Aborting startup." >&2
    exit 1
fi

# ── Start application ──────────────────────────────────────────────
echo ""
echo "--- Starting OpenArtifact ---"
exec uvicorn \
    openartifact.app:create_app \
    --host "${OPENARTIFACT_HOST}" \
    --port "${OPENARTIFACT_PORT}" \
    --log-level "${LOG_LEVEL_LOWER}" \
    --timeout-graceful-shutdown 3 \
    --factory

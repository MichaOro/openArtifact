#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# OpenArtifact Docker entrypoint
#
# 1. Run Alembic migrations to initialize or upgrade the database (under the data directory lock)
# 2. Start the application (the openartifact command)
#
# All configuration via OPENARTIFACT_ environment variables.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# The settings (host, port, log level, data directory) are read by the application itself from the
# OPENARTIFACT_ environment; the defaults live in openartifact/config.py.
DATA_DIR="${OPENARTIFACT_DATA_DIR:-/data}"
echo "=== OpenArtifact Docker Entrypoint ==="
echo "Data directory: ${DATA_DIR}"

# ── Database migration ─────────────────────────────────────────────
echo ""
echo "--- Running database migrations ---"
cd /app

# Under the lock of the data directory (ADR-094): while another OpenArtifact process uses it, this
# container is refused here, before it migrates the database that process serves.
if python -m openartifact.process_lock alembic upgrade head; then
    echo "Migrations completed successfully."
else
    status=$?
    if [ "$status" -eq 3 ]; then
        echo "ERROR: The data directory is in use by another OpenArtifact process. Aborting startup." >&2
        exit 3
    fi
    echo "ERROR: Database migration failed. Aborting startup." >&2
    exit 1
fi

# ── Start application ──────────────────────────────────────────────
echo ""
echo "--- Starting OpenArtifact ---"
# The same command as outside the image (openartifact.cli), so logging and shutdown behave the same.
# Behind a TLS-terminating proxy set FORWARDED_ALLOW_IPS (read by uvicorn) to the proxy's address, so
# that X-Forwarded-Proto is trusted and the session cookie is issued as Secure.
exec openartifact

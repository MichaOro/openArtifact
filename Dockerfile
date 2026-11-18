# ── Stage 1: Build ────────────────────────────────────────────────
# Install dependencies and build wheels in a full Python image.
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only dependency definitions first for better layer caching
COPY apps/backend/pyproject.toml apps/backend/.python-version ./

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -e .

# Copy application source code
COPY apps/backend/openartifact/ openartifact/

# ── Stage 2: Runtime ──────────────────────────────────────────────
# Minimal image with only installed wheels and application source.
FROM python:3.12-slim AS runtime

# Non-root user for container security
RUN groupadd --gid 1000 openartifact \
    && useradd --uid 1000 --gid openartifact --create-home --shell /bin/bash openartifact

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

COPY --from=builder /build/openartifact openartifact/

# Copy alembic configuration
COPY apps/backend/alembic.ini ./
COPY apps/backend/alembic/ alembic/

# Create persistent data directory with correct ownership
RUN mkdir -p /data \
    && chown -R openartifact:openartifact /data \
    && chown openartifact:openartifact /app \
    && chown -R openartifact:openartifact /app/apps/backend

# Expose application port
EXPOSE 2909

# Switch to non-root user
USER openartifact

# Entry point: run Alembic migrations, then start the application
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

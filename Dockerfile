# ── Stage 1: Build ────────────────────────────────────────────────
# Install dependencies and build wheels in a full Python image.
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only dependency metadata first so the dependency layer stays cached
# until pyproject.toml changes.
COPY apps/backend/pyproject.toml apps/backend/.python-version README.md ./

# Install runtime dependencies (read from pyproject.toml) before the source
# is copied, so code-only changes do not reinstall them.
RUN pip install --no-cache-dir --upgrade pip \
    && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# Copy application source code
COPY apps/backend/openartifact/ openartifact/

# Install the package itself (non-editable); dependencies are already present
RUN pip install --no-cache-dir --prefix=/install --no-deps .

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

# Copy entrypoint script
COPY scripts/docker-entrypoint.sh scripts/docker-entrypoint.sh
RUN chmod +x scripts/docker-entrypoint.sh \
    && chown openartifact:openartifact scripts/docker-entrypoint.sh

# Create persistent data directory with correct ownership
RUN mkdir -p /data \
    && chown -R openartifact:openartifact /data \
    && chown openartifact:openartifact /app \
    && chown -R openartifact:openartifact /app/openartifact

# Expose application port
EXPOSE 2909

# Switch to non-root user
USER openartifact

# Ensure openartifact package is importable from /app
ENV PYTHONPATH=/app

# Entry point: run Alembic migrations, then start the application
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

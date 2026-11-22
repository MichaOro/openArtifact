# ── Stage 1: Build ────────────────────────────────────────────────
# Resolve the runtime dependencies and install them with the package into /install.
FROM python:3.12-slim AS builder

WORKDIR /build

# The backend README is the package's readme (pyproject.toml: readme = "README.md").
COPY apps/backend/pyproject.toml ./
COPY apps/backend/README.md ./README.md

# Dependencies come before the source so that code-only changes keep this layer cached.
RUN pip install --no-cache-dir --upgrade pip \
    && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY apps/backend/openartifact/ openartifact/
RUN pip install --no-cache-dir --prefix=/install --no-deps .

# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1000 openartifact \
    && useradd --uid 1000 --gid openartifact --create-home --shell /bin/bash openartifact

WORKDIR /app

# The package is installed once, in site-packages. Everything under /app belongs to root and is
# read-only for the runtime user; only /data is writable.
COPY --from=builder /install /usr/local
COPY apps/backend/alembic.ini ./
COPY apps/backend/alembic/ alembic/
COPY --chmod=755 scripts/docker-entrypoint.sh scripts/docker-entrypoint.sh

RUN mkdir -p /data && chown openartifact:openartifact /data

ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 2909

USER openartifact

# The entrypoint runs the Alembic migrations, then starts the application.
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

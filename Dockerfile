# Base images are pinned by digest (multi-arch index); Dependabot (docker) proposes updates.
# uv is used in the builder only, to export the locked runtime dependencies; the runtime stage has no uv.
FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

# ── Stage 1: Build ────────────────────────────────────────────────
# Install exactly the runtime dependencies of uv.lock, then the package, into /install.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS builder

WORKDIR /build

# The repository README is the package's readme (pyproject.toml: readme = "README.md").
COPY pyproject.toml uv.lock README.md ./

# Dependencies come before the source so that code-only changes keep this layer cached.
# --frozen takes uv.lock as written (CI checks that it is current); the export carries the hashes and pip refuses
# any file without a matching one.
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt \
    && pip install --no-cache-dir --prefix=/install --require-hashes --no-deps -r requirements.txt

COPY openartifact/ openartifact/
RUN pip install --no-cache-dir --prefix=/install --no-deps .

# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS runtime

RUN groupadd --gid 1000 openartifact \
    && useradd --uid 1000 --gid openartifact --create-home --shell /bin/bash openartifact

WORKDIR /app

# The package is installed once, in site-packages. Everything under /app belongs to root and is
# read-only for the runtime user; only /data is writable.
COPY --from=builder /install /usr/local
COPY alembic.ini ./
COPY alembic/ alembic/
COPY --chmod=755 scripts/docker-entrypoint.sh scripts/docker-entrypoint.sh

RUN mkdir -p /data && chown openartifact:openartifact /data

ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 2909

USER openartifact

# The entrypoint runs the Alembic migrations, then starts the application.
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

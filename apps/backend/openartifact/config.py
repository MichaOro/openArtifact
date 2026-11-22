"""Application configuration.

All settings are externalized via environment variables with the
OPENARTIFACT_ prefix. No secrets or hardcoded paths are embedded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-in-production"
MIN_TOKEN_LENGTH = 32


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Configuration groups: server (host, port, debug), database (data directory and file name),
    security (secret key, API token, hosts, cookie, limits), engine limits and logging.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENARTIFACT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Server ──────────────────────────────────────────────────────

    host: str = "0.0.0.0"
    port: int = 2909
    debug: bool = False

    # ── Database ────────────────────────────────────────────────────
    # Database path is composed from data_dir + database_filename
    # to keep the location configurable and external to source.
    data_dir: Path = Path("/data")
    database_filename: str = "openartifact.db"

    # ── Security ────────────────────────────────────────────────────
    secret_key: str = DEFAULT_SECRET_KEY
    #: The one access token (at least 32 characters): the whole application asks for it, as a bearer
    #: header or through the sign-in page. Empty: the pages and the browser API are open, and the
    #: integration API (``/api/v1``) and the MCP server (``/mcp``) refuse everything (401).
    api_token: str = ""
    #: Host names the application answers to, comma separated (``example.com, *.example.org``); a
    #: ``Host`` header outside the list is refused (protects against DNS rebinding). Empty: no check.
    allowed_hosts: str = ""
    #: Whether the session cookie is ``Secure`` (and named ``__Host-oa_session``): ``auto`` follows the
    #: request scheme, ``true`` is right behind a TLS-terminating proxy.
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    #: Largest request body in bytes; a larger one gets ``413``.
    max_request_bytes: int = 1024 * 1024
    #: Opt-out only: adds ``'unsafe-inline'`` to the script policy. The pages have no inline scripts, so
    #: the default policy is ``script-src 'self'``.
    csp_script_unsafe_inline: bool = False

    # ── Engine limits ───────────────────────────────────────────────
    #: Runs that may be active at the same time; a further start is refused with ``429``.
    max_concurrent_runs: int = 8
    #: Open event streams (browser tabs); a further one gets ``503``.
    max_sse_subscribers: int = 50

    # ── Logging ─────────────────────────────────────────────────────
    log_level: str = "INFO"

    @property
    def allowed_host_list(self) -> list[str]:
        """The ``allowed_hosts`` setting as a list of lower-case patterns."""
        return [h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()]

    def security_problems(self) -> list[str]:
        """What makes the security settings unusable (the application refuses to start with these)."""
        problems: list[str] = []
        if self.api_token:
            if len(self.api_token) < MIN_TOKEN_LENGTH:
                problems.append(
                    f"OPENARTIFACT_API_TOKEN must have at least {MIN_TOKEN_LENGTH} characters "
                    "(for example: openssl rand -hex 32)"
                )
            if not self.secret_key or self.secret_key == DEFAULT_SECRET_KEY:
                problems.append(
                    "OPENARTIFACT_SECRET_KEY must be set to a secret of your own when an API token "
                    "is used (it signs the session cookie)"
                )
        return problems

    @property
    def database_url(self) -> str:
        """The async SQLAlchemy URL of the SQLite file (``data_dir`` / ``database_filename``).

        WAL mode is not part of the URL; the engine switches it on per connection (see ``database.py``).
        """
        return f"sqlite+aiosqlite:///{self.data_dir / self.database_filename}"

    @property
    def is_production(self) -> bool:
        """Whether this is a production run (anything but debug mode)."""
        return not self.debug


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Uses lru_cache to avoid reloading settings on every call.
    Settings are loaded from environment variables with OPENARTIFACT_ prefix
    and fallback .env file.
    """
    return Settings()

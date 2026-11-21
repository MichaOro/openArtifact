"""Application configuration.

All settings are externalized via environment variables with the
OPENARTIFACT_ prefix. No secrets or hardcoded paths are embedded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Configuration groups:
    - Server: host, port, debug mode
    - Database: data directory and database filename (combined into URL)
    - Security: secret key for signing
    - Logging: log level
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
    secret_key: str = "change-me-in-production"
    #: Token for the integration API (``/api/v1``) and the MCP server (``/mcp``). Empty: both are
    #: switched off (401), because they would otherwise be open to anyone who can reach the port.
    api_token: str = ""

    # ── Logging ─────────────────────────────────────────────────────
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        """Construct the async SQLAlchemy database URL.

        Combines data_dir and database_filename into a full SQLite
        async URL with WAL mode enabled for better concurrent read
        performance.
        """
        db_path = self.data_dir / self.database_filename
        # Use file:// URI scheme for aiosqlite to handle absolute paths
        db_uri = f"sqlite+aiosqlite:///{db_path}"
        return db_uri

    @property
    def is_production(self) -> bool:
        """Return True when running in production mode."""
        return not self.debug


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Uses lru_cache to avoid reloading settings on every call.
    Settings are loaded from environment variables with OPENARTIFACT_ prefix
    and fallback .env file.
    """
    return Settings()

"""Application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All configuration is externalized. No secrets are embedded in source code.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENARTIFACT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 2909
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./openartifact.db"

    # Security
    secret_key: str = "change-me-in-production"

    # Logging
    log_level: str = "INFO"

    # Application data directory
    data_dir: Path = Path("/data")

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

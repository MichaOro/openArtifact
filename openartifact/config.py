"""Application configuration.

All settings are externalized via environment variables with the
OPENARTIFACT_ prefix. No secrets or hardcoded paths are embedded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-in-production"
MIN_TOKEN_LENGTH = 32
MIN_SECRET_KEY_LENGTH = 32


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
    port: int = Field(default=2909, ge=1, le=65535)
    debug: bool = False

    # ── Database ────────────────────────────────────────────────────
    # Database path is composed from data_dir + database_filename
    # to keep the location configurable and external to source.
    data_dir: Path = Path("/data")
    database_filename: str = "openartifact.db"

    # ── Security ────────────────────────────────────────────────────
    #: Signs the session cookie and, through a derived key, encrypts the stored credentials. At least 32
    #: characters as soon as a token is set (``python -c "import secrets; print(secrets.token_hex(32))"``).
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
    max_request_bytes: int = Field(default=1024 * 1024, ge=1024, le=1024**3)
    #: Opt-out only: adds ``'unsafe-inline'`` to the script policy. The pages have no inline scripts, so
    #: the default policy is ``script-src 'self'``.
    csp_script_unsafe_inline: bool = False

    # ── Engine limits ───────────────────────────────────────────────
    #: Runs that may be active at the same time; a further start is refused with ``429``.
    max_concurrent_runs: int = Field(default=8, ge=1, le=1024)
    #: Open event streams (browser tabs); a further one gets ``503``.
    max_sse_subscribers: int = Field(default=50, ge=1, le=100000)

    # ── Execution history ───────────────────────────────────────────
    #: How many executions of an artifact are kept when its owner has set no retention policy of its
    #: own; the oldest finished ones beyond that are deleted. ``0`` keeps all of them: the database then
    #: grows with every run (outputs of up to 1 MiB each), so use it only with a policy per artifact.
    execution_history_default_keep: int = Field(default=50, ge=0, le=100000)

    # ── Code and HTTP nodes ─────────────────────────────────────────
    #: Whether Code nodes run. Code runs as a child of the application with the application's own
    #: rights (no sandbox); off: a Code node fails with "Code nodes are disabled".
    code_nodes_enabled: bool = True
    #: Code nodes in *open mode* (no ``api_token``). Off by default: without a token everyone who reaches
    #: the port can create and run a Code node, i.e. run commands as the application's user, so Code
    #: nodes then fail with an explanation. Switch on only for local development on a trusted machine.
    code_nodes_without_token: bool = False
    #: Largest stdout and stderr (each, in bytes) kept of a Code node; the rest is cut off.
    code_output_limit_bytes: int = Field(default=65536, ge=1024, le=64 * 1024 * 1024)
    #: Largest response body (bytes) an HTTP node reads; the rest is cut off.
    http_response_limit_bytes: int = Field(default=1024 * 1024, ge=1024, le=1024**3)
    #: Whether HTTP nodes may call loopback, private, link-local and metadata addresses. Off by
    #: default (protects the host network); self-hosters calling their own services switch it on.
    http_allow_private_networks: bool = False
    #: Whether an LLM provider may be on a loopback, private or link-local address (a model server on
    #: this host or in the internal network). It is the operator's half of the permission: a provider
    #: must also have its own ``allow_private`` switched on. It does not open HTTP nodes
    #: (``http_allow_private_networks`` does), and cloud metadata addresses stay refused.
    llm_allow_private_networks: bool = False

    #: Address space (virtual memory) of a Code node's process in MiB (``RLIMIT_AS``). Python and the
    #: shell need little; runtimes that reserve much address space (Java, Node.js, Go) need more.
    code_memory_limit_mb: int = Field(default=512, ge=64, le=65536)
    #: Processes and threads a Code node may add (``RLIMIT_NPROC``). The kernel counts per user, not
    #: per process tree, so the limit is the user's current count plus this number. Does not apply
    #: to a process that runs as root.
    code_process_limit: int = Field(default=64, ge=1, le=4096)
    #: Largest file in MiB a Code node's process may write (``RLIMIT_FSIZE``).
    code_file_size_limit_mb: int = Field(default=64, ge=1, le=10240)
    #: Open files of a Code node's process (``RLIMIT_NOFILE``).
    code_open_files_limit: int = Field(default=256, ge=16, le=65536)

    # ── Logging ─────────────────────────────────────────────────────
    #: Python log level name, case-insensitive (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``).
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

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
            elif len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
                problems.append(
                    f"OPENARTIFACT_SECRET_KEY must have at least {MIN_SECRET_KEY_LENGTH} characters "
                    "when an API token is used (it signs the session cookie and encrypts stored "
                    'credentials; for example: python -c "import secrets; print(secrets.token_hex(32))")'
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

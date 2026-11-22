"""CLI entry point (``openartifact``): the one way the server is started, by hand and in the image.

Logging is configured by the application factory itself, so it does not depend on who starts it.
"""

from __future__ import annotations

import sys

import uvicorn
from uvicorn.config import LOG_LEVELS

from openartifact.config import get_settings


def main() -> None:
    """Start uvicorn with the application; Ctrl+C or SIGTERM ends it gracefully."""
    settings = get_settings()
    level = settings.log_level.lower()

    config = uvicorn.Config(
        "openartifact.app:create_app",
        host=settings.host,
        port=settings.port,
        log_level=level if level in LOG_LEVELS else "info",
        factory=True,
        # an open event stream (a browser tab) must not hold up the shutdown
        timeout_graceful_shutdown=3,
    )
    try:
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()

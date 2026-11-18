"""CLI entry point for OpenArtifact.

Starts the uvicorn server with the configured application.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from openartifact.config import get_settings
from openartifact.logging_config import configure_logging


def main() -> None:
    """Main entry point.

    Configures logging and starts uvicorn with the FastAPI application.
    Supports graceful shutdown via Ctrl+C.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    logger = logging.getLogger("openartifact")

    # Configure uvicorn log level based on application log level
    uvicorn_level = "debug" if settings.debug else "info"

    config = uvicorn.Config(
        "openartifact.app:create_app",
        host=settings.host,
        port=settings.port,
        log_level=uvicorn_level,
        factory=True,
        access_log=False,  # We handle logging ourselves
    )
    server = uvicorn.Server(config)

    try:
        logger.info("Starting OpenArtifact on %s:%d", settings.host, settings.port)
        server.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()

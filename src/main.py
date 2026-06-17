"""ASGI entrypoint: MCP streamable-HTTP app wrapped with Entra auth."""
from __future__ import annotations

import logging

import uvicorn

from .auth import AuthMiddleware
from .config import settings
from .server import mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pubmed_connector")

# Mount the MCP streamable-HTTP endpoint at the configured path (default /mcp).
mcp.settings.streamable_http_path = settings.mcp_path

# Build the Starlette ASGI app and wrap it with bearer-token validation.
app = AuthMiddleware(mcp.streamable_http_app())


def main() -> None:
    problems = settings.validate_for_auth()
    if problems:
        for problem in problems:
            logger.error("Configuration error: %s", problem)
        raise SystemExit(1)

    if not settings.auth_required:
        logger.warning(
            "AUTH_REQUIRED is false - the MCP server is running WITHOUT "
            "authentication. Use this only for local testing or initial deploy."
        )

    logger.info("Starting PubMed MCP server on port %s, path %s", settings.port, settings.mcp_path)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()

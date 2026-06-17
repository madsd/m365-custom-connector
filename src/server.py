"""MCP server exposing read-only PubMed tools for Microsoft 365 Copilot.

Implements the `search` / `fetch` tool contract that Copilot federated
connectors use to discover and retrieve grounding content.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings
from .pubmed import PubMedClient

mcp = FastMCP(
    name="PubMed Connector",
    instructions=(
        "Search and retrieve biomedical literature from the public PubMed "
        "database. Use `search` to find articles by topic, then `fetch` to "
        "read an article's abstract and metadata by its PMID."
    ),
    stateless_http=True,
    # The public Azure Container Apps FQDN differs from the container host, so
    # configure the transport-security (DNS-rebinding) allow-list explicitly.
    # "*" disables the host/origin check; access is still gated by Entra
    # bearer-token validation in AuthMiddleware. Set ALLOWED_HOSTS to specific
    # hostnames to enable strict DNS-rebinding protection.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection="*" not in settings.allowed_hosts,
        allowed_hosts=[h for h in settings.allowed_hosts if h != "*"],
        allowed_origins=[o for o in settings.allowed_origins if o != "*"],
    ),
)

_client = PubMedClient()


@mcp.tool()
async def search(query: str, max_results: int = 10) -> dict:
    """Search PubMed for biomedical articles matching a query.

    Args:
        query: A free-text search, e.g. "CRISPR gene editing sickle cell".
        max_results: Maximum number of results to return (1-50).

    Returns:
        An object with a `results` list. Each result has `id` (PubMed PMID),
        `title`, `url`, and a `snippet` with authors/journal/date.
    """
    results = await _client.search(query, max_results)
    return {"results": results}


@mcp.tool()
async def fetch(id: str) -> dict:
    """Fetch a single PubMed article by its PMID.

    Args:
        id: The PubMed identifier (PMID), e.g. "38000000".

    Returns:
        An object with `id`, `title`, `text` (the abstract), `url`, and
        `metadata` (journal, authors, publication date, DOI).
    """
    summary = await _client.summary(id)
    if summary is None:
        return {
            "id": id,
            "title": "",
            "text": f"No PubMed article found for PMID {id}.",
            "url": "",
            "metadata": {},
        }
    abstract = await _client.fetch_abstract(id)
    return {
        "id": summary["id"],
        "title": summary["title"],
        "text": abstract or summary.get("snippet", ""),
        "url": summary["url"],
        "metadata": summary.get("metadata", {}),
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})

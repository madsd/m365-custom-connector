"""Quick end-to-end smoke test against a running MCP server."""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _payload(result) -> dict:
    """Return the tool result as a dict from structuredContent or JSON text."""
    if result.structuredContent:
        return result.structuredContent
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    return {}


async def main(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])

            res = await session.call_tool("search", {"query": "CRISPR sickle cell", "max_results": 3})
            results = _payload(res).get("results", [])
            print(f"SEARCH returned {len(results)} results")
            for r in results:
                print("  -", r["id"], r["title"][:70])

            if results:
                pmid = results[0]["id"]
                fres = await session.call_tool("fetch", {"id": pmid})
                fdata = _payload(fres)
                print(f"FETCH {pmid}: title={fdata.get('title','')[:60]!r}")
                print("  abstract chars:", len(fdata.get("text", "")))
                print("  metadata:", fdata.get("metadata"))


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"
    asyncio.run(main(url))

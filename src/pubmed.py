"""Async client for the NCBI PubMed E-utilities API.

PubMed is a public database, so no data-source credentials are required. An
optional NCBI API key raises the request rate limit from 3 to 10 requests/sec.
Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""
from __future__ import annotations

import asyncio
import time

import httpx

from .config import settings

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


class PubMedClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=EUTILS_BASE, timeout=30.0)
        # NCBI allows 3 requests/sec without an API key, 10/sec with one.
        # Serialize requests and space them out to stay under the limit.
        self._lock = asyncio.Lock()
        self._min_interval = 0.11 if settings.ncbi_api_key else 0.34
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    def _common_params(self) -> dict[str, str]:
        params = {"db": "pubmed", "tool": settings.ncbi_tool}
        if settings.ncbi_email:
            params["email"] = settings.ncbi_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        return params

    async def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        """GET with client-side throttling and retry on throttle/5xx."""
        last_exc: Exception | None = None
        for attempt in range(4):
            async with self._lock:
                wait = self._min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._client.get(path, params=params)
                finally:
                    self._last_request = time.monotonic()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"NCBI returned {resp.status_code}", request=resp.request, response=resp
                )
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            resp.raise_for_status()
            return resp
        assert last_exc is not None
        raise last_exc

    async def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Search PubMed and return lightweight result records."""
        max_results = max(1, min(int(max_results), 50))
        params = self._common_params()
        params.update(
            {
                "term": query,
                "retmax": str(max_results),
                "retmode": "json",
                "sort": "relevance",
            }
        )
        resp = await self._get("/esearch.fcgi", params)
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        return await self.summaries(ids)

    async def summaries(self, pmids: list[str]) -> list[dict]:
        params = self._common_params()
        params.update({"id": ",".join(pmids), "retmode": "json"})
        resp = await self._get("/esummary.fcgi", params)
        result = resp.json().get("result", {})
        out: list[dict] = []
        for pmid in result.get("uids", []):
            doc = result.get(pmid, {})
            out.append(
                {
                    "id": pmid,
                    "title": (doc.get("title") or "").rstrip("."),
                    "url": ARTICLE_URL.format(pmid=pmid),
                    "snippet": _summary_snippet(doc),
                }
            )
        return out

    async def summary(self, pmid: str) -> dict | None:
        doc_meta = await self._raw_summary(pmid)
        if doc_meta is None:
            return None
        return {
            "id": pmid,
            "title": doc_meta.pop("title", ""),
            "url": ARTICLE_URL.format(pmid=pmid),
            "snippet": doc_meta.pop("snippet", ""),
            "metadata": doc_meta,
        }

    async def _raw_summary(self, pmid: str) -> dict | None:
        params = self._common_params()
        params.update({"id": pmid, "retmode": "json"})
        resp = await self._get("/esummary.fcgi", params)
        result = resp.json().get("result", {})
        doc = result.get(pmid)
        if not doc or "error" in doc:
            return None
        authors = [a.get("name", "") for a in doc.get("authors", []) if a.get("name")]
        return {
            "title": (doc.get("title") or "").rstrip("."),
            "snippet": _summary_snippet(doc),
            "journal": doc.get("fulljournalname") or doc.get("source", ""),
            "pubdate": doc.get("pubdate", ""),
            "authors": authors,
            "doi": doc.get("elocationid", ""),
            "pmid": pmid,
        }

    async def fetch_abstract(self, pmid: str) -> str:
        params = self._common_params()
        params.update({"id": pmid, "rettype": "abstract", "retmode": "text"})
        resp = await self._get("/efetch.fcgi", params)
        return resp.text.strip()


def _summary_snippet(doc: dict) -> str:
    author_list = doc.get("authors", [])
    authors = ", ".join(a.get("name", "") for a in author_list[:3])
    if len(author_list) > 3:
        authors += ", et al."
    source = doc.get("source", "")
    pubdate = doc.get("pubdate", "")
    parts = [p for p in (authors, source, pubdate) if p]
    return " \u2014 ".join(parts)

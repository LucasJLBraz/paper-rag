"""Semantic Scholar Graph API — search + direct open-access PDF links.

Works without an API key at a low rate limit; pass one via
acquire.semantic_scholar_api_key in .paper-rag.toml to raise it.
"""
from __future__ import annotations

import requests

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,externalIds,openAccessPdf,abstract"


def search(query: str, api_key: str = "", limit: int = 5) -> list[dict]:
    headers = {"x-api-key": api_key} if api_key else {}
    params = {"query": query, "limit": limit, "fields": FIELDS}
    r = requests.get(API, params=params, headers=headers, timeout=30)
    r.raise_for_status()

    results = []
    for p in r.json().get("data", []):
        oa = p.get("openAccessPdf") or {}
        results.append(
            {
                "title": p.get("title"),
                "doi": (p.get("externalIds") or {}).get("DOI"),
                "authors": [a["name"] for a in p.get("authors", [])],
                "year": p.get("year"),
                "pdf_url": oa.get("url"),
                "abstract": p.get("abstract"),
                "semantic_scholar_id": p.get("paperId"),
            }
        )
    return results

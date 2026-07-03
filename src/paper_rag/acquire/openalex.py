"""OpenAlex search — free, no API key required, generous rate limits."""
from __future__ import annotations

import requests

API = "https://api.openalex.org/works"


def search(query: str, contact_email: str = "", limit: int = 5) -> list[dict]:
    params = {"search": query, "per_page": limit, "mailto": contact_email or None}
    r = requests.get(API, params={k: v for k, v in params.items() if v}, timeout=30)
    r.raise_for_status()

    results = []
    for w in r.json().get("results", []):
        best_oa = w.get("best_oa_location") or {}
        results.append(
            {
                "title": w.get("title"),
                "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                "year": w.get("publication_year"),
                "pdf_url": best_oa.get("pdf_url"),
                "abstract": None,
                "openalex_id": w.get("id"),
            }
        )
    return results

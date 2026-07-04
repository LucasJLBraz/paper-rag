"""OpenAlex search — free, no API key required, generous rate limits."""
from __future__ import annotations

import requests

API = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    # OpenAlex doesn't return plain-text abstracts (copyright reasons) — only
    # a word -> token-position map. Invert it back into ordered text.
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


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
                "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
                "openalex_id": w.get("id"),
            }
        )
    return results

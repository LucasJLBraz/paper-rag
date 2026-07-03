"""Fallback chain for finding a legally open-access PDF for a query.

Order: Semantic Scholar (often has a direct OA PDF link already) -> if only
a DOI, resolve via Unpaywall -> repeat against OpenAlex. Stops at the first
hit with a usable pdf_url.
"""
from __future__ import annotations

from . import openalex, semantic_scholar, unpaywall


def find_oa_pdf(query: str, contact_email: str, s2_api_key: str = "") -> dict | None:
    for hit in semantic_scholar.search(query, api_key=s2_api_key, limit=3):
        if hit.get("pdf_url"):
            return {**hit, "source": "semantic_scholar"}
        if hit.get("doi"):
            oa = unpaywall.resolve(hit["doi"], contact_email)
            if oa:
                return {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall"}

    for hit in openalex.search(query, contact_email, limit=3):
        if hit.get("pdf_url"):
            return {**hit, "source": "openalex"}
        if hit.get("doi"):
            oa = unpaywall.resolve(hit["doi"], contact_email)
            if oa:
                return {**hit, "pdf_url": oa["pdf_url"], "source": "unpaywall"}

    return None

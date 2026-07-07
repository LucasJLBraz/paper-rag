"""Keyword-overlap relevance scoring shared by resolve.py (title/DOI match
confidence) and discover.py (topical search ranking).
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def relevance(query: str, hit: dict) -> float:
    """Fraction of the query's meaningful terms found in the hit's title + abstract."""
    query_terms = set(_TOKEN_RE.findall(query.lower()))
    if not query_terms:
        return 1.0
    haystack = f"{hit.get('title') or ''} {hit.get('abstract') or ''}".lower()
    haystack_terms = set(_TOKEN_RE.findall(haystack))
    return len(query_terms & haystack_terms) / len(query_terms)

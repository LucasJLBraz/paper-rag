"""Shared "is this the same paper" normalization.

Used by discover.py's within-call, cross-source dedup (Semantic Scholar
vs. OpenAlex) and cache.py's cross-call dedup (this discover_papers() call
vs. everything already in discover_cache.json) — kept in one place so the
two can't quietly drift apart.
"""
from __future__ import annotations

import re

_DOI_PREFIX_RE = re.compile(r"^https?://doi\.org/", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def natural_key(hit: dict) -> str | None:
    """Normalized doi (preferred) or title key for `hit`, or None if it has
    neither. Callers decide what "no natural key" means for their own
    fallback: discover.py assigns a per-call-unique key (two hits with no
    identifying info can't be proven to be the same paper, but also
    shouldn't collide onto the same bogus key); cache.py treats it as
    always-new for the same reason."""
    doi = (hit.get("doi") or "").strip()
    if doi:
        return "doi:" + _DOI_PREFIX_RE.sub("", doi).lower()
    title = _WHITESPACE_RE.sub(" ", (hit.get("title") or "").strip().lower())
    if title:
        return "title:" + title
    return None

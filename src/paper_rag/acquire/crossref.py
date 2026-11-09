"""Crossref — exact metadata lookup for a known DOI. Free, no API key."""
from __future__ import annotations

import re

import requests


def lookup(doi: str, contact_email: str = "") -> dict | None:
    """Metadata for `doi`, in the same hit shape as the search sources, or
    None if Crossref does not know the DOI."""
    r = requests.get(
        f"https://api.crossref.org/works/{doi}",
        params={"mailto": contact_email} if contact_email else None,
        timeout=30,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    w = r.json()["message"]
    date_parts = (w.get("issued") or w.get("published") or {}).get("date-parts") or [[None]]
    return {
        "title": (w.get("title") or [None])[0],
        "doi": w.get("DOI") or doi,
        "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in w.get("author", [])],
        "year": date_parts[0][0],
        "venue": (w.get("container-title") or [None])[0],
        # Crossref abstracts are JATS XML; tags only, the text is kept.
        "abstract": re.sub(r"<[^>]+>", "", w.get("abstract") or "").strip(),
    }

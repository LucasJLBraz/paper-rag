"""arXiv — exact lookup by arXiv id. Free, no API key."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def lookup(arxiv_id: str) -> dict | None:
    """Metadata + PDF URL for `arxiv_id` (for example 2401.01234v2), or None."""
    r = requests.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id}, timeout=30)
    r.raise_for_status()
    entry = ET.fromstring(r.text).find(f"{_ATOM}entry")
    # An unknown id returns either no entry or an entry with no title.
    if entry is None or not (entry.findtext(f"{_ATOM}title") or "").strip():
        return None
    return {
        "title": " ".join(entry.findtext(f"{_ATOM}title").split()),
        "doi": entry.findtext(f"{_ARXIV}doi"),
        "authors": [a.findtext(f"{_ATOM}name") for a in entry.findall(f"{_ATOM}author")],
        "year": int(entry.findtext(f"{_ATOM}published")[:4]),
        "venue": "arXiv",
        "abstract": " ".join((entry.findtext(f"{_ATOM}summary") or "").split()),
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }

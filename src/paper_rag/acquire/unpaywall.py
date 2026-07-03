"""Unpaywall — resolves a DOI to a legal open-access PDF location.

Requires a contact email (their "polite pool" terms) — set
acquire.contact_email in .paper-rag.toml.
"""
from __future__ import annotations

import requests


def resolve(doi: str, contact_email: str) -> dict | None:
    if not doi:
        return None
    if not contact_email:
        raise ValueError("Unpaywall requires acquire.contact_email to be set in .paper-rag.toml")

    r = requests.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": contact_email}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()

    best = r.json().get("best_oa_location")
    if not best or not best.get("url_for_pdf"):
        return None
    return {"pdf_url": best["url_for_pdf"], "license": best.get("license")}

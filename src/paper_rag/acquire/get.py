"""Shared single-candidate download logic for a discover() result.

Used by both the CLI `get` command (cli.py) and the MCP `get_paper` tool
(mcp_server.py) so citation-key generation, lazy Unpaywall resolution, and
metadata writing only exist once.
"""
from __future__ import annotations

from pathlib import Path

from . import download, metadata, unpaywall


def download_candidate(
    hit: dict,
    contact_email: str,
    papers_dir: Path,
    root: Path,
    citation_key: str | None,
    fallback_title: str,
) -> dict:
    """Resolve (if needed) + download one discover() candidate.

    Returns {"status": "ok", "citation_key", "pdf_path", "source"} on
    success, or {"status": "error", "error"} on failure — never raises, so
    a batch of ids (cli.py's `get`, mcp_server.py's `get_paper`) can report
    per-item results without one failure aborting the rest.
    """
    pdf_url = hit.get("pdf_url")
    source = hit.get("source", "unknown")

    if not pdf_url and hit.get("doi"):
        try:
            oa = unpaywall.resolve(hit["doi"], contact_email)
        except Exception as e:
            return {"status": "error", "error": f"Unpaywall lookup failed: {e!r}"}
        if oa:
            pdf_url = oa["pdf_url"]
            source = "unpaywall"

    if not pdf_url:
        title = hit.get("title") or "(no title)"
        return {"status": "error", "error": f'No open-access PDF available for "{title}" — try downloading it manually.'}

    try:
        pdf_content = download.fetch_pdf_bytes(pdf_url)
    except Exception as e:
        return {"status": "error", "error": f"Download failed: {e!r}"}

    resolved_citation_key = citation_key or metadata.make_citation_key(
        hit.get("title") or fallback_title, hit.get("authors", []), hit.get("year")
    )
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = papers_dir / f"{resolved_citation_key}.pdf"
    md_path = papers_dir / f"{resolved_citation_key}.md"
    pdf_path.write_bytes(pdf_content)
    metadata.write_metadata(
        md_path,
        resolved_citation_key,
        hit.get("title") or fallback_title,
        hit.get("authors", []),
        hit.get("year"),
        hit.get("doi"),
        source,
        pdf_url,
        pdf_path.relative_to(root),
        hit.get("abstract") or "",
    )
    return {
        "status": "ok",
        "citation_key": resolved_citation_key,
        "pdf_path": str(pdf_path.relative_to(root)),
        "source": source,
    }

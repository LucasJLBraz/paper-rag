"""Shared single-candidate download logic for a discover() result.

Used by both the CLI `get` command (cli.py) and the MCP `get_paper` tool
(mcp_server.py) so citation-key generation, lazy Unpaywall resolution, and
metadata writing only exist once.
"""
from __future__ import annotations

from pathlib import Path

from . import download, metadata, unpaywall
from .download import InvalidPdfContentError


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
    success; {"status": "exists", ...same fields} without downloading when
    a paper with the same DOI already has its PDF in papers_dir; {"status": "invalid_content", "error"} if the downloaded
    bytes aren't a real PDF (e.g. an anti-bot/cookie-wall page served with
    HTTP 200 — see acquire/download.py); or {"status": "error", "error"}
    on any other failure. Never raises, so a batch of ids (cli.py's `get`,
    mcp_server.py's `get_paper`) can report per-item results without one
    failure aborting the rest.
    """
    pdf_url = hit.get("pdf_url")
    source = hit.get("source", "unknown")

    existing = metadata.find_by_doi(papers_dir, hit.get("doi"))
    if existing and (papers_dir / f"{existing}.pdf").exists():
        return {
            "status": "exists",
            "citation_key": existing,
            "pdf_path": str((papers_dir / f"{existing}.pdf").relative_to(root)),
            "source": source,
        }

    if not pdf_url and hit.get("doi"):
        try:
            oa = unpaywall.resolve(hit["doi"], contact_email)
            if oa:
                resolved_pdf_url = oa.get("pdf_url")
                if resolved_pdf_url:
                    pdf_url = resolved_pdf_url
                    source = "unpaywall"
        except Exception as e:
            return {"status": "error", "error": f"Unpaywall lookup failed: {e!r}"}
    if not pdf_url:
        title = hit.get("title") or "(no title)"
        return {"status": "error", "error": f'No open-access PDF available for "{title}" — try downloading it manually.'}

    try:
        pdf_content = download.fetch_pdf_bytes(pdf_url)
    except InvalidPdfContentError as e:
        return {"status": "invalid_content", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": f"Download failed: {e!r}"}

    try:
        papers_dir.mkdir(parents=True, exist_ok=True)
        if citation_key:
            metadata.check_explicit_key(papers_dir, citation_key, pdf_content)
        resolved_citation_key = citation_key or existing or metadata.free_citation_key(
            papers_dir,
            metadata.make_citation_key(hit.get("title") or fallback_title, hit.get("authors", []), hit.get("year")),
            pdf_content,
        )
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
            hit.get("venue") or "",
        )
    except Exception as e:
        return {"status": "error", "error": f"Failed to save downloaded PDF: {e!r}"}

    return {
        "status": "ok",
        "citation_key": resolved_citation_key,
        "pdf_path": str(pdf_path.relative_to(root)),
        "source": source,
    }

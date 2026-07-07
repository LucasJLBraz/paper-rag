"""Write a companion metadata .md — schema-compatible with the arxiv-paper-fetch
skill's convention (citation_key, title, authors, published, abstract), extended
with `source`/`doi` since papers here didn't necessarily come from arXiv.
"""
from __future__ import annotations

import re
from pathlib import Path

_STOPWORDS = {
    "a", "an", "the", "on", "of", "for", "and", "to", "in", "with",
    "towards", "toward", "using", "via", "how", "why", "what", "is",
    "are", "into", "from", "as",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _yaml_double_quote(text: str) -> str:
    """Escape backslashes and double-quotes for a YAML double-quoted scalar."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def make_citation_key(title: str, authors: list[str], year) -> str:
    surname = _slug(authors[0].split()[-1]) if authors else "unknown"
    year = year or "nd"
    words = [_slug(w) for w in (title or "").split()]
    word = next((w for w in words if w and w not in _STOPWORDS and len(w) > 2), "paper")
    return f"{surname}{year}{word}"


def write_metadata(
    md_path: Path,
    citation_key: str,
    title: str,
    authors: list[str],
    year,
    doi: str | None,
    source: str,
    pdf_url: str,
    pdf_path: Path,
    abstract: str = "",
) -> None:
    authors_yaml = "\n".join(f"  - {a}" for a in authors) or "  - unknown"
    frontmatter = (
        "---\n"
        f"citation_key: {citation_key}\n"
        f"doi: {doi or ''}\n"
        f'title: "{_yaml_double_quote(title)}"\n'
        f"authors:\n{authors_yaml}\n"
        f"published: {year or 'n.d.'}\n"
        f"source: {source}\n"
        f"source_url: {pdf_url}\n"
        f"pdf: {pdf_path.as_posix()}\n"
        "---\n\n"
        "## Abstract\n\n"
        f"{(abstract or '').strip()}\n"
    )
    md_path.write_text(frontmatter)

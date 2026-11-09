"""Write a companion metadata .md — schema-compatible with the arxiv-paper-fetch
skill's convention (citation_key, title, authors, published, abstract), extended
with `source`/`doi` since papers here didn't necessarily come from arXiv.
"""
from __future__ import annotations

import re
import string
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
    venue: str = "",
) -> None:
    authors_yaml = "\n".join(f"  - {a}" for a in authors) or "  - unknown"
    frontmatter = (
        "---\n"
        f"citation_key: {citation_key}\n"
        f"doi: {doi or ''}\n"
        f'title: "{_yaml_double_quote(title)}"\n'
        f"authors:\n{authors_yaml}\n"
        f"published: {year or 'n.d.'}\n"
        f'venue: "{_yaml_double_quote(venue or "")}"\n'
        f"source: {source}\n"
        f"source_url: {pdf_url}\n"
        f"pdf: {pdf_path.as_posix()}\n"
        "---\n\n"
        "## Abstract\n\n"
        f"{(abstract or '').strip()}\n"
    )
    md_path.write_text(frontmatter)


_DOI_LINE = re.compile(r"^doi:\s*(\S+)\s*$", re.MULTILINE)


def _norm_doi(doi: str) -> str:
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def find_by_doi(papers_dir: Path, doi: str | None) -> str | None:
    """citation_key of the companion .md in papers_dir whose `doi:` matches,
    or None. Used to avoid downloading a paper the corpus already has."""
    if not doi or not papers_dir.is_dir():
        return None
    wanted = _norm_doi(doi)
    # ponytail: linear scan of every .md per call; fine for a few thousand papers.
    for md in sorted(papers_dir.glob("*.md")):
        m = _DOI_LINE.search(md.read_text(errors="ignore")[:2000])
        if m and _norm_doi(m.group(1)) == wanted:
            return md.stem
    return None


def check_explicit_key(papers_dir: Path, key: str, pdf_content: bytes | None) -> str:
    """A user-given --citation-key must not overwrite another paper."""
    if free_citation_key(papers_dir, key, pdf_content) != key:
        raise FileExistsError(f"citation key {key} is already used by another paper in {papers_dir}")
    return key


def free_citation_key(papers_dir: Path, key: str, pdf_content: bytes | None) -> str:
    """`key`, or `key` + b/c/... when `key` is already taken by another paper.
    Generated keys collide easily (smith2020deep), and writing over the
    existing files would silently replace a paper in the corpus."""
    for suffix in ("",) + tuple(string.ascii_lowercase[1:]):
        candidate = key + suffix
        pdf, md = papers_dir / f"{candidate}.pdf", papers_dir / f"{candidate}.md"
        if not pdf.exists() and not md.exists():
            return candidate
        if pdf_content is not None and pdf.exists() and pdf.read_bytes() == pdf_content:
            return candidate  # same file: rewriting it changes nothing
    raise FileExistsError(f"citation keys {key} to {key}z are all taken in {papers_dir}")

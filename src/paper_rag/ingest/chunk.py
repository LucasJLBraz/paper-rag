"""Section-aware, token-bounded chunking for academic markdown.

Splits on markdown headings first (so a chunk never straddles, say, Methods
and Results), drops the References/Bibliography section by default (it's
citation noise, not retrievable content), then sub-splits each section by
paragraph with a token-count ceiling and a small trailing overlap so a
concept split across a chunk boundary is still findable from either side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENC = None


def count_tokens(text: str) -> int:
    if _ENC is not None:
        return len(_ENC.encode(text))
    return max(1, len(text) // 4)  # rough fallback if tiktoken isn't installed


_REFERENCES_HEADING = re.compile(r"^#{1,3}\s*(references|bibliography)\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


@dataclass
class Chunk:
    section: str
    text: str
    token_count: int


def split_sections(markdown: str, drop_references: bool = True) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = "front matter"
    current_lines: list[str] = []
    dropping = False

    def flush():
        if current_lines and not dropping:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_heading, body))

    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            current_heading = m.group(2).strip()
            current_lines = []
            dropping = drop_references and bool(_REFERENCES_HEADING.match(line))
        else:
            current_lines.append(line)
    flush()
    return sections


def chunk_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)
        if buf and buf_tokens + para_tokens > max_tokens:
            chunks.append("\n\n".join(buf))
            overlap_buf: list[str] = []
            overlap_count = 0
            for p in reversed(buf):
                t = count_tokens(p)
                if overlap_count + t > overlap_tokens:
                    break
                overlap_buf.insert(0, p)
                overlap_count += t
            buf, buf_tokens = overlap_buf, overlap_count
        buf.append(para)
        buf_tokens += para_tokens

    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def chunk_markdown(
    markdown: str,
    max_tokens: int = 400,
    overlap_tokens: int = 60,
    drop_references: bool = True,
) -> list[Chunk]:
    result: list[Chunk] = []
    for heading, body in split_sections(markdown, drop_references=drop_references):
        for piece in chunk_text(body, max_tokens, overlap_tokens):
            result.append(Chunk(section=heading, text=piece, token_count=count_tokens(piece)))
    return result

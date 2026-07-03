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


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_CELL = re.compile(r"^:?-+:?$")
_TABLE_CAPTION_MAX_TOKENS = 80
_TABLE_ROWS_PER_CHUNK = 4


def _is_table(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    if len(lines) < 2 or not (_TABLE_ROW.match(lines[0]) and _TABLE_ROW.match(lines[1])):
        return False
    sep_cells = [c.strip() for c in _row_cells(lines[1])]
    return bool(sep_cells) and all(_TABLE_SEP_CELL.match(c) for c in sep_cells if c)


def _row_cells(row: str) -> list[str]:
    # A plain .strip("|") would eat a genuinely empty first/last cell along
    # with the delimiter pipe (e.g. "||Original|58|" -> "Original|58",
    # silently dropping a column) — trim exactly one delimiter on each side.
    cells = row.strip().split("|")
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _fill_merged_cells(rows: list[str]) -> list[str]:
    """Fill blank cells left by pymupdf4llm's flattening of row-spanned cells.

    A cell that spans several rows (e.g. a dataset name next to a block of
    per-method metric rows) gets its label written on only one row of the
    span — not necessarily the first — leaving the rest of that column
    blank for the other rows. Left as-is, splitting the table into row
    batches would separate a data row from the one row that says which
    group it belongs to. Nearest-neighbor fill (by row distance, in either
    direction) reconstructs the label for every row without assuming which
    row of the span originally carried it.
    """
    parsed = [_row_cells(row) for row in rows]
    if not parsed:
        return rows
    n_cols = max(len(r) for r in parsed)
    for col in range(n_cols):
        values = [r[col] if col < len(r) else "" for r in parsed]
        non_empty = [i for i, v in enumerate(values) if v.strip()]
        if not non_empty:
            continue
        for i, v in enumerate(values):
            if v.strip() or col >= len(parsed[i]):
                continue
            nearest = min(non_empty, key=lambda j: abs(j - i))
            parsed[i][col] = values[nearest]
    return ["|" + "|".join(r) + "|" for r in parsed]


def _split_table(paragraph: str, caption: str | None) -> list[str]:
    header, sep, *rows = [line for line in paragraph.splitlines() if line.strip()]
    rows = _fill_merged_cells(rows)
    prefix = f"{caption}\n\n" if caption else ""
    return [
        prefix + "\n".join([header, sep, *rows[i : i + _TABLE_ROWS_PER_CHUNK]])
        for i in range(0, len(rows), _TABLE_ROWS_PER_CHUNK)
    ]


def _expand_tables(paragraphs: list[str]) -> list[tuple[str, bool]]:
    """Mark table paragraphs and split them into small, row-batched pieces.

    A whole markdown table embedded as one chunk (the default paragraph
    unit) produces one embedding diluted across every row/model in it — a
    query about one specific row can't be matched against it. Splitting by
    a few rows at a time, with the table's caption and header repeated in
    each piece for context, keeps each chunk's embedding anchored to the
    handful of facts it actually answers.
    """
    out: list[tuple[str, bool]] = []
    for para in paragraphs:
        if _is_table(para):
            caption = None
            if out and not out[-1][1] and count_tokens(out[-1][0]) <= _TABLE_CAPTION_MAX_TOKENS:
                caption = out.pop()[0]
            out.extend((piece, True) for piece in _split_table(para, caption))
        else:
            out.append((para, False))
    return out


def chunk_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces = _expand_tables(paragraphs)
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    def flush(carry_overlap: bool) -> None:
        nonlocal buf, buf_tokens
        if not buf:
            return
        chunks.append("\n\n".join(buf))
        if not carry_overlap:
            buf, buf_tokens = [], 0
            return
        overlap_buf: list[str] = []
        overlap_count = 0
        for p in reversed(buf):
            t = count_tokens(p)
            if overlap_count + t > overlap_tokens:
                break
            overlap_buf.insert(0, p)
            overlap_count += t
        buf, buf_tokens = overlap_buf, overlap_count

    for para, is_table_piece in pieces:
        if is_table_piece:
            # Table pieces are already small and self-contained — never
            # merge them with neighboring prose, or the dilution problem
            # this exists to fix comes right back.
            flush(carry_overlap=False)
            chunks.append(para)
            continue
        para_tokens = count_tokens(para)
        if buf and buf_tokens + para_tokens > max_tokens:
            flush(carry_overlap=True)
        buf.append(para)
        buf_tokens += para_tokens

    flush(carry_overlap=False)
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

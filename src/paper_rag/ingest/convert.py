"""PDF -> Markdown conversion. Local-only, no network calls, no data leaves the machine."""
from __future__ import annotations

from pathlib import Path


def pdf_to_markdown(pdf_path: Path) -> str:
    try:
        import pymupdf4llm
    except ImportError as e:
        raise RuntimeError(
            "pymupdf4llm is required for PDF conversion: pip install pymupdf4llm"
        ) from e
    return pymupdf4llm.to_markdown(str(pdf_path))

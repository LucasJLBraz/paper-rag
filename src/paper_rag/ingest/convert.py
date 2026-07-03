"""PDF -> Markdown conversion. Local-only, no network calls, no data leaves the machine."""
from __future__ import annotations

import signal
from pathlib import Path


class ConversionTimeout(Exception):
    pass


def _raise_timeout(signum, frame):
    raise ConversionTimeout("pdf_to_markdown exceeded the configured timeout")


def pdf_to_markdown(pdf_path: Path, timeout_seconds: int = 120) -> str:
    """Convert a PDF to markdown via pymupdf4llm.

    Malformed academic PDFs (corrupt xref/dict entries) can make the
    underlying MuPDF parser spin for a very long time recovering objects
    instead of raising a catchable error — a single such paper can hang an
    entire batch build. Bound the conversion with a SIGALRM timeout
    (Unix-only) so the caller can skip that one paper and move on.
    """
    try:
        import pymupdf4llm
    except ImportError as e:
        raise RuntimeError(
            "pymupdf4llm is required for PDF conversion: pip install pymupdf4llm"
        ) from e

    if timeout_seconds and hasattr(signal, "SIGALRM"):
        previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(timeout_seconds)
        try:
            return pymupdf4llm.to_markdown(str(pdf_path))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)

    return pymupdf4llm.to_markdown(str(pdf_path))

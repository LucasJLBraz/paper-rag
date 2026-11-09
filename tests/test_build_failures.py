import argparse
from unittest.mock import patch

import pytest

from paper_rag.cli import cmd_build
from paper_rag.ingest.convert import pdf_to_markdown


def _make_pdf(path, text):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(path))


def test_pdf_to_markdown_smoke(tmp_path):
    # Real conversion, no mocks: catches a dependency upgrade that breaks
    # pymupdf4llm.to_markdown (pymupdf4llm 2.x shipped without it, #4).
    pdf = tmp_path / "smoke.pdf"
    _make_pdf(pdf, "Atrial fibrillation smoke test")
    assert "Atrial fibrillation smoke test" in pdf_to_markdown(pdf)


class _FakeBackend:
    name = "fake"
    dim = 4

    def embed(self, texts, is_query=False):
        return [[0.0] * 4 for _ in texts]


def test_build_exits_nonzero_and_summarizes_when_a_paper_fails(tmp_path, capsys):
    config = tmp_path / ".paper-rag.toml"
    config.write_text('[corpus]\npapers_dir = "papers"\n[index]\ndir = ".rag_index"\n')
    papers = tmp_path / "papers"
    papers.mkdir()
    _make_pdf(papers / "good.pdf", "Good paper body text")
    _make_pdf(papers / "bad.pdf", "Bad paper body text")

    real = pdf_to_markdown

    def flaky(path, timeout_seconds=120):
        if path.stem == "bad":
            raise AttributeError("module 'pymupdf4llm' has no attribute 'to_markdown'")
        return real(path, timeout_seconds)

    with patch("paper_rag.cli.build_backend", return_value=_FakeBackend()), patch(
        "paper_rag.cli.pdf_to_markdown", side_effect=flaky
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_build(argparse.Namespace(config=str(config), rebuild=False))

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "1 of 2 paper(s) failed" in err
    assert "bad" in err

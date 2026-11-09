import argparse
from unittest.mock import patch

import pytest

from paper_rag.acquire import metadata
from paper_rag.acquire.get import download_candidate
from paper_rag.cli import cmd_acquire, cmd_add


def _config(tmp_path):
    p = tmp_path / ".paper-rag.toml"
    p.write_text('[corpus]\npapers_dir = "papers"\n[acquire]\ncontact_email = "t@example.org"\n')
    (tmp_path / "papers").mkdir()
    return str(p)


def _paper(tmp_path, key, doi, pdf=b"%PDF-old"):
    papers = tmp_path / "papers"
    if pdf is not None:
        (papers / f"{key}.pdf").write_bytes(pdf)
    (papers / f"{key}.md").write_text(f"---\ncitation_key: {key}\ndoi: {doi}\n---\n")


def test_free_citation_key_suffixes_instead_of_overwriting(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "zhang2020deep.pdf").write_bytes(b"%PDF-a")
    (papers / "zhang2020deep.md").write_text("x")
    assert metadata.free_citation_key(papers, "zhang2020deep", b"%PDF-b") == "zhang2020deepb"
    assert metadata.free_citation_key(papers, "zhang2020deep", b"%PDF-a") == "zhang2020deep"


def test_find_by_doi_is_case_and_prefix_insensitive(tmp_path):
    _config(tmp_path)
    _paper(tmp_path, "choi2024machine", "10.1161/jaha.123.034154")
    assert metadata.find_by_doi(tmp_path / "papers", "https://doi.org/10.1161/JAHA.123.034154") == "choi2024machine"
    assert metadata.find_by_doi(tmp_path / "papers", "10.1/other") is None


HIT = {"title": "Deep nets", "authors": ["Wei Zhang"], "year": 2020, "doi": "10.1/new", "pdf_url": "https://x/p.pdf",
       "source": "openalex", "relevance": 1.0}


def test_acquire_collision_gets_suffix_and_keeps_old_paper(tmp_path):
    cfg = _config(tmp_path)
    _paper(tmp_path, "zhang2020deep", "10.1/old")
    with patch("paper_rag.acquire.resolve.find_oa_pdf_candidates", return_value=[HIT]), patch(
        "paper_rag.acquire.download.fetch_pdf_bytes", return_value=b"%PDF-new"
    ):
        cmd_acquire(argparse.Namespace(config=cfg, query="Deep nets", citation_key=None))
    assert (tmp_path / "papers" / "zhang2020deep.pdf").read_bytes() == b"%PDF-old"
    assert (tmp_path / "papers" / "zhang2020deepb.pdf").read_bytes() == b"%PDF-new"


def test_acquire_explicit_key_never_overwrites(tmp_path):
    cfg = _config(tmp_path)
    _paper(tmp_path, "mykey", "10.1/old")
    with patch("paper_rag.acquire.resolve.find_oa_pdf_candidates", return_value=[HIT]), patch(
        "paper_rag.acquire.download.fetch_pdf_bytes", return_value=b"%PDF-new"
    ):
        with pytest.raises(SystemExit):
            cmd_acquire(argparse.Namespace(config=cfg, query="Deep nets", citation_key="mykey"))
    assert (tmp_path / "papers" / "mykey.pdf").read_bytes() == b"%PDF-old"


def test_acquire_skips_download_when_doi_already_in_corpus(tmp_path, capsys):
    cfg = _config(tmp_path)
    _paper(tmp_path, "zhang2020deep", "10.1/new")
    with patch("paper_rag.acquire.resolve.find_oa_pdf_candidates", return_value=[HIT]), patch(
        "paper_rag.acquire.download.fetch_pdf_bytes"
    ) as fetch:
        cmd_acquire(argparse.Namespace(config=cfg, query="Deep nets", citation_key=None))
    assert not fetch.called
    assert "Already in the corpus as zhang2020deep" in capsys.readouterr().out


def test_add_completes_metadata_only_entry_in_place(tmp_path):
    cfg = _config(tmp_path)
    _paper(tmp_path, "choi2024machine", "10.1161/jaha.123.034154", pdf=None)
    src = tmp_path / "dl.pdf"
    src.write_bytes(b"%PDF-1.4")
    meta = {"title": "Machine learning AF", "doi": "10.1161/jaha.123.034154", "authors": ["Ana Choi"], "year": 2024}
    with patch("paper_rag.acquire.crossref.lookup", return_value=meta):
        cmd_add(argparse.Namespace(config=cfg, pdf=str(src), doi=meta["doi"], citation_key=None))
    assert sorted(p.name for p in (tmp_path / "papers").iterdir()) == ["choi2024machine.md", "choi2024machine.pdf"]


def test_get_reports_exists_without_downloading(tmp_path):
    _config(tmp_path)
    _paper(tmp_path, "zhang2020deep", "10.1/new")
    with patch("paper_rag.acquire.download.fetch_pdf_bytes") as fetch:
        r = download_candidate(HIT, "t@example.org", tmp_path / "papers", tmp_path, None, "q")
    assert r["status"] == "exists" and r["citation_key"] == "zhang2020deep"
    assert not fetch.called

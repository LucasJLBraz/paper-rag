import argparse
from unittest.mock import MagicMock, patch

import pytest

from paper_rag.acquire import arxiv, resolve
from paper_rag.cli import cmd_acquire, cmd_add


def _config(tmp_path):
    p = tmp_path / ".paper-rag.toml"
    p.write_text('[corpus]\npapers_dir = "papers"\n[acquire]\ncontact_email = "test@example.com"\n')
    return str(p)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("10.1161/JAHA.123.034154", ("doi", "10.1161/JAHA.123.034154")),
        ("https://doi.org/10.1109/TBME.2019.2909027", ("doi", "10.1109/TBME.2019.2909027")),
        ("arXiv:2401.01234v2", ("arxiv", "2401.01234v2")),
        ("https://arxiv.org/pdf/2401.01234", ("arxiv", "2401.01234")),
        ("https://doi.org/10.48550/arXiv.2401.01234", ("arxiv", "2401.01234")),
        ("COPA: Constrained PARAFAC2 for Sparse & Large Datasets", None),
    ],
)
def test_parse_identifier(query, expected):
    assert resolve.parse_identifier(query) == expected


META = {"title": "Real JAHA paper", "doi": "10.1161/JAHA.123.034154", "authors": ["Ana Choi"], "year": 2024, "abstract": ""}


def test_doi_query_never_runs_keyword_search(tmp_path, capsys):
    with patch("paper_rag.acquire.crossref.lookup", return_value=META), patch(
        "paper_rag.acquire.unpaywall.resolve_all", return_value=["https://blocked/x.pdf", "https://pmc/x.pdf"]
    ), patch("paper_rag.acquire.resolve.find_oa_pdf_candidates") as keyword, patch(
        "paper_rag.acquire.download.fetch_pdf_bytes",
        side_effect=lambda url, *a, **k: (_ for _ in ()).throw(Exception("403")) if "blocked" in url else b"%PDF-1.4",
    ):
        cmd_acquire(argparse.Namespace(config=_config(tmp_path), query="10.1161/JAHA.123.034154", citation_key=None))

    assert not keyword.called
    [pdf] = (tmp_path / "papers").glob("*.pdf")
    assert pdf.name == "choi2024real.pdf"
    assert "source_url: https://pmc/x.pdf" in pdf.with_suffix(".md").read_text()


def test_doi_without_open_pdf_writes_metadata_only(tmp_path, capsys):
    with patch("paper_rag.acquire.crossref.lookup", return_value=META), patch(
        "paper_rag.acquire.unpaywall.resolve_all", return_value=[]
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_acquire(argparse.Namespace(config=_config(tmp_path), query="10.1161/JAHA.123.034154", citation_key=None))

    assert exc.value.code == 1
    assert not list((tmp_path / "papers").glob("*.pdf"))
    assert "Real JAHA paper" in (tmp_path / "papers" / "choi2024real.md").read_text()
    assert "No open PDF" in capsys.readouterr().err


def test_unknown_doi_writes_nothing(tmp_path):
    with patch("paper_rag.acquire.crossref.lookup", return_value=None):
        with pytest.raises(SystemExit):
            cmd_acquire(argparse.Namespace(config=_config(tmp_path), query="10.9999/nope", citation_key=None))
    assert not (tmp_path / "papers").exists()


ATOM = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><title>Deep  Survival
 Models</title><summary> An abstract. </summary><published>2023-05-01T00:00:00Z</published>
<author><name>Jane Lee</name></author><arxiv:doi>10.1000/x</arxiv:doi></entry></feed>"""


def test_arxiv_lookup_parses_atom():
    resp = MagicMock(text=ATOM)
    with patch("paper_rag.acquire.arxiv.requests.get", return_value=resp):
        meta = arxiv.lookup("2305.00001")
    assert meta == {
        "title": "Deep Survival Models",
        "doi": "10.1000/x",
        "authors": ["Jane Lee"],
        "year": 2023,
        "abstract": "An abstract.",
        "pdf_url": "https://arxiv.org/pdf/2305.00001",
    }


def test_arxiv_lookup_unknown_id():
    resp = MagicMock(text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    with patch("paper_rag.acquire.arxiv.requests.get", return_value=resp):
        assert arxiv.lookup("9999.99999") is None


def test_add_copies_pdf_with_crossref_metadata(tmp_path):
    src = tmp_path / "download.pdf"
    src.write_bytes(b"%PDF-1.4 body")
    with patch("paper_rag.acquire.crossref.lookup", return_value=META):
        cmd_add(argparse.Namespace(config=_config(tmp_path), pdf=str(src), doi=META["doi"], citation_key=None))
    assert (tmp_path / "papers" / "choi2024real.pdf").read_bytes() == b"%PDF-1.4 body"
    assert "source: manual" in (tmp_path / "papers" / "choi2024real.md").read_text()


def test_add_rejects_non_pdf(tmp_path):
    src = tmp_path / "page.pdf"
    src.write_text("<html>")
    with pytest.raises(SystemExit):
        cmd_add(argparse.Namespace(config=_config(tmp_path), pdf=str(src), doi=None, citation_key=None))
    assert not (tmp_path / "papers").exists()

from paper_rag.acquire.metadata import make_citation_key, write_metadata
from pathlib import Path


def test_make_citation_key_basic():
    key = make_citation_key("A Survey on Tabular Data Generation", ["Jane Smith"], 2024)
    assert key == "smith2024survey"


def test_make_citation_key_no_authors():
    key = make_citation_key("Untitled", [], None)
    assert key.startswith("unknownnd")


def test_write_metadata_roundtrip(tmp_path):
    md_path = tmp_path / "smith2024survey.md"
    write_metadata(
        md_path,
        "smith2024survey",
        "A Survey on Tabular Data Generation",
        ["Jane Smith"],
        2024,
        "10.1234/abcd",
        "openalex",
        "https://example.com/paper.pdf",
        Path("references/Papers/smith2024survey.pdf"),
        "This is the abstract.",
    )
    content = md_path.read_text()
    assert "citation_key: smith2024survey" in content
    assert "doi: 10.1234/abcd" in content
    assert "This is the abstract." in content

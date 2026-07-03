from paper_rag.ingest.chunk import chunk_markdown, split_sections


def test_drops_references_section():
    md = """# Abstract

Some abstract text.

## References

Smith et al 2024. Some Paper.
"""
    sections = split_sections(md, drop_references=True)
    headings = [h for h, _ in sections]
    assert "References" not in headings
    assert "Abstract" in headings


def test_keeps_references_when_not_dropping():
    md = """# Abstract

Some abstract text.

## References

Smith et al 2024. Some Paper.
"""
    sections = split_sections(md, drop_references=False)
    headings = [h for h, _ in sections]
    assert "References" in headings


def test_chunk_markdown_respects_token_budget():
    md = "# Methods\n\n" + "\n\n".join(f"Paragraph {i} with some words in it." for i in range(20))
    chunks = chunk_markdown(md, max_tokens=20, overlap_tokens=5)
    assert len(chunks) > 1
    assert all(c.section == "Methods" for c in chunks)


def test_chunk_markdown_empty_input():
    assert chunk_markdown("") == []

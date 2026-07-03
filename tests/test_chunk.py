from paper_rag.ingest.chunk import chunk_markdown, chunk_text, split_sections


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


def test_large_table_is_split_into_row_batches_not_one_chunk():
    caption = "TABLE 3 Fidelity results for the acute myeloid leukemia dataset."
    header = "|Model|Hellinger distance|PCD|"
    sep = "|---|---|---|"
    rows = [f"|Model{i}|0.{i}|0.{i}|" for i in range(12)]
    table = "\n".join([header, sep, *rows])
    md = f"{caption}\n\n{table}"

    chunks = chunk_text(md, max_tokens=400, overlap_tokens=60)

    assert len(chunks) > 1
    for c in chunks:
        assert header in c
        assert caption in c
        data_rows = [row for row in rows if row in c]
        assert 0 < len(data_rows) <= 4  # a handful of rows per chunk, not all 12


def test_table_rows_carry_caption_and_header_context():
    md = "Table 1: results.\n\n|A|B|\n|---|---|\n|x|1|\n|y|2|\n|z|3|\n|w|4|\n|v|5|"
    chunks = chunk_text(md, max_tokens=400, overlap_tokens=60)
    assert len(chunks) == 2
    assert all("Table 1: results." in c and "|A|B|" in c for c in chunks)


def test_table_row_span_group_label_is_filled_into_every_row():
    # Mirrors pymupdf4llm's flattening of a row-spanned "Dataset" cell: the
    # label lands on one row of the group (here, the 4th of 7), not the first.
    header = "|Dataset|Method|F1|"
    sep = "|---|---|---|"
    travel = ["||Original|58|", "||TVAE|60|", "||CopulaGAN|22|", "|Travel|CTABGAN+|55|", "||GReaT|61|", "||TabDDPM|53|", "||Ours|67|"]
    sick = ["||Original|88|", "||TVAE|88|", "||CopulaGAN|84|", "|Sick|CTABGAN+|82|", "||GReaT|87|", "||TabDDPM|85|", "||Ours|89|"]
    table = "\n".join([header, sep, *travel, *sick])

    chunks = chunk_text(table, max_tokens=400, overlap_tokens=0)

    ours_travel_chunk = next(c for c in chunks if "Ours|67" in c)
    assert "Travel" in ours_travel_chunk
    ours_sick_chunk = next(c for c in chunks if "Ours|89" in c)
    assert "Sick" in ours_sick_chunk
    assert "Travel" not in ours_sick_chunk

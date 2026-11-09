from paper_rag import mcp_server
from paper_rag.ingest.index import PaperIndex


class _FakeBackend:
    name = "fake-test-model"
    dim = 4

    def embed(self, texts, is_query=False):
        return [[0.0, 0.0, 0.0, 0.0] for _ in texts]


def _write_config(tmp_path):
    config_path = tmp_path / ".paper-rag.toml"
    config_path.write_text(
        """
[corpus]
papers_dir = "papers"

[index]
dir = ".rag_index"

[acquire]
contact_email = "test@example.com"
"""
    )
    return config_path


def _row(citation_key):
    return {
        "chunk_id": f"{citation_key}::0",
        "citation_key": citation_key,
        "section": "Abstract",
        "text": "some text",
        "token_count": 3,
        "pdf_path": f"{citation_key}.pdf",
        "embedding_model": "fake-test-model",
        "vector": [0.0, 0.0, 0.0, 0.0],
    }


def test_list_indexed_papers_sees_rows_added_by_a_separate_build_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(mcp_server, "build_backend", lambda *a, **k: _FakeBackend())
    mcp_server._state.clear()

    assert mcp_server.list_indexed_papers() == []

    # Simulate a separate `paper-rag build` (CLI) process writing to the
    # same on-disk index after the MCP server already opened this table
    # handle — a second PaperIndex instance, not the one cached in
    # mcp_server._state.
    external_index = PaperIndex(tmp_path / ".rag_index", "chunks", 4, "fake-test-model")
    external_table = external_index.open_or_create()
    external_index.add(external_table, [_row("newpaper2026")])

    assert mcp_server.list_indexed_papers() == ["newpaper2026"]

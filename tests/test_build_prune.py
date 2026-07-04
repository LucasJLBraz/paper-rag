import argparse
import json
from unittest.mock import patch

from paper_rag.cli import cmd_build
from paper_rag.ingest.index import PaperIndex


class _FakeBackend:
    name = "fake-embedding-model"
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
"""
    )
    return config_path


def _run_build(config_path, rebuild=False):
    with patch("paper_rag.cli.build_backend", return_value=_FakeBackend()):
        cmd_build(argparse.Namespace(config=str(config_path), rebuild=rebuild))


def test_build_prunes_manifest_and_table_entries_for_deleted_pdf(tmp_path):
    config_path = _write_config(tmp_path)
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir()

    # Seed the table + manifest as if "deleted_paper" was previously indexed,
    # but its PDF is gone by the time `build` runs now.
    index = PaperIndex(index_dir, "chunks", 4, "fake-embedding-model")
    table = index.open_or_create()
    index.add(
        table,
        [
            {
                "chunk_id": "deleted_paper::0",
                "citation_key": "deleted_paper",
                "section": "Intro",
                "text": "stale text",
                "token_count": 2,
                "pdf_path": "papers/deleted_paper.pdf",
                "embedding_model": "fake-embedding-model",
                "vector": [0.0, 0.0, 0.0, 0.0],
            }
        ],
    )
    (index_dir / "manifest.json").write_text(json.dumps({"deleted_paper": "abc123"}))

    _run_build(config_path)

    manifest = json.loads((index_dir / "manifest.json").read_text())
    assert "deleted_paper" not in manifest

    table = index.open_or_create()
    assert "deleted_paper" not in index.distinct_citation_keys(table)


def test_build_prunes_table_entry_missing_from_manifest(tmp_path):
    # Simulates an interrupted run: the row made it into the table (index.add)
    # but the manifest flush never happened.
    config_path = _write_config(tmp_path)
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    index_dir = tmp_path / ".rag_index"
    index_dir.mkdir()

    index = PaperIndex(index_dir, "chunks", 4, "fake-embedding-model")
    table = index.open_or_create()
    index.add(
        table,
        [
            {
                "chunk_id": "orphan::0",
                "citation_key": "orphan",
                "section": "Intro",
                "text": "stale text",
                "token_count": 2,
                "pdf_path": "papers/orphan.pdf",
                "embedding_model": "fake-embedding-model",
                "vector": [0.0, 0.0, 0.0, 0.0],
            }
        ],
    )
    # No manifest.json at all.

    _run_build(config_path)

    table = index.open_or_create()
    assert "orphan" not in index.distinct_citation_keys(table)

import pytest

from paper_rag.config import load_config


def test_load_config_defaults(tmp_path):
    (tmp_path / ".paper-rag.toml").write_text("")
    cfg = load_config(str(tmp_path / ".paper-rag.toml"))
    assert cfg.corpus.papers_dir == "references/Papers"
    assert cfg.embedding.model == "BAAI/bge-m3"
    assert cfg.chunking.max_tokens == 400


def test_load_config_overrides(tmp_path):
    (tmp_path / ".paper-rag.toml").write_text(
        """
[corpus]
papers_dir = "papers"

[embedding]
backend = "ollama"
model = "nomic-embed-text"
"""
    )
    cfg = load_config(str(tmp_path / ".paper-rag.toml"))
    assert cfg.corpus.papers_dir == "papers"
    assert cfg.embedding.backend == "ollama"
    assert cfg.embedding.model == "nomic-embed-text"


def test_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_config()

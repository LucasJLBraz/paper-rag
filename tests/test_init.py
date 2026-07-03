import argparse
import json

from paper_rag.cli import cmd_init


def _run_init(tmp_path, email=None):
    cmd_init(argparse.Namespace(dir=str(tmp_path), email=email))


def test_init_writes_expected_files(tmp_path):
    _run_init(tmp_path, email="me@example.com")

    assert (tmp_path / ".paper-rag.toml").exists()
    assert "me@example.com" in (tmp_path / ".paper-rag.toml").read_text()
    assert (tmp_path / ".claude" / "skills" / "paper-rag" / "SKILL.md").exists()

    mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp_config["mcpServers"]["paper-rag"] == {"command": "paper-rag-mcp"}

    assert ".rag_index/" in (tmp_path / ".gitignore").read_text().splitlines()


def test_init_does_not_clobber_existing_config(tmp_path):
    _run_init(tmp_path, email="first@example.com")
    _run_init(tmp_path, email="second@example.com")

    assert "first@example.com" in (tmp_path / ".paper-rag.toml").read_text()
    assert "second@example.com" not in (tmp_path / ".paper-rag.toml").read_text()


def test_init_does_not_duplicate_gitignore_entry(tmp_path):
    _run_init(tmp_path)
    _run_init(tmp_path)

    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count(".rag_index/") == 1


def test_init_preserves_other_gitignore_entries(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc\n")
    _run_init(tmp_path)

    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert "node_modules/" in lines
    assert "*.pyc" in lines
    assert ".rag_index/" in lines


def test_init_preserves_existing_mcp_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other-tool": {"command": "other-cmd"}}}))
    _run_init(tmp_path)

    mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp_config["mcpServers"]["other-tool"] == {"command": "other-cmd"}
    assert mcp_config["mcpServers"]["paper-rag"] == {"command": "paper-rag-mcp"}


def test_init_refreshes_skill_file_to_installed_version(tmp_path):
    _run_init(tmp_path)
    skill_path = tmp_path / ".claude" / "skills" / "paper-rag" / "SKILL.md"
    skill_path.write_text("hand-edited content")

    _run_init(tmp_path)

    assert skill_path.read_text() != "hand-edited content"

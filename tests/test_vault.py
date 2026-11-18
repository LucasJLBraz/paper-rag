import pytest

from paper_rag.config import load_config
from paper_rag.vault import VaultError, send


def _setup(tmp_path, vault="vault"):
    repo = tmp_path / "vlmc_af_nsr"
    papers = repo / "papers"
    papers.mkdir(parents=True)
    (repo / ".paper-rag.toml").write_text(
        f'[corpus]\npapers_dir = "papers"\n[obsidian]\nvault_dir = "{tmp_path / vault}"\n'
    )
    (papers / "choi2024machine.pdf").write_bytes(b"%PDF-1.4")
    (papers / "choi2024machine.md").write_text(
        '---\ncitation_key: choi2024machine\ntitle: "ML for AF"\npdf: papers/choi2024machine.pdf\n---\n\n## Abstract\n\nText.\n'
    )
    return load_config(str(repo / ".paper-rag.toml"))


def test_send_creates_pdf_and_metadata_card(tmp_path):
    cfg = _setup(tmp_path)
    r = send(cfg, "choi2024machine", "features")

    target = tmp_path / "vault" / "vlmc_af_nsr" / "features"
    assert (target / "choi2024machine.pdf").read_bytes() == b"%PDF-1.4"
    card = (target / "choi2024machine.md").read_text()
    head, body = card.split("\n---\n", 1)
    assert 'title: "ML for AF"' in head
    assert "papers/" not in head
    assert 'pdf: "[[choi2024machine.pdf]]"\ntipo: paper\npesquisa: vlmc_af_nsr\nsubtopico: features\ndata: ' in head
    assert 'zotflow-local-attachment: "[[choi2024machine.pdf]]"' in head
    assert "\nvisao_geral: false\nconteudo: false\na_fundo: false" in head
    for h in ("## Em uma frase", "## 1ª passagem", "## 2ª passagem", "## 3ª passagem", "## Minhas ideias", "## Sobre o paper"):
        assert h in body
    assert "<!-- ZF_PERSIST_BEG_sobre -->\n### Abstract\n\nText.\n<!-- ZF_PERSIST_END_sobre -->" in body
    assert body.count("ZF_PERSIST_BEG_") == body.count("ZF_PERSIST_END_") == 7
    assert "{{" not in body
    assert "Leitura.base#Desta pasta" in (target / "00 Papers.md").read_text()
    assert not (target / "@choi2024machine.md").exists()
    assert r["pdf_status"] == r["note_status"] == "created"


def test_card_without_abstract_has_only_the_link(tmp_path):
    cfg = _setup(tmp_path)
    (tmp_path / "vlmc_af_nsr" / "papers" / "choi2024machine.md").write_text(
        "---\ncitation_key: choi2024machine\npdf: papers/choi2024machine.pdf\n---\n\n## Abstract\n\n"
    )
    send(cfg, "choi2024machine", "features")
    card = (tmp_path / "vault" / "vlmc_af_nsr" / "features" / "choi2024machine.md").read_text()
    assert "<!-- ZF_PERSIST_BEG_sobre -->\n\n<!-- ZF_PERSIST_END_sobre -->" in card
    assert "pdf: papers/" not in card


def test_send_twice_never_overwrites_annotated_note(tmp_path):
    cfg = _setup(tmp_path)
    send(cfg, "choi2024machine", "features")
    note = tmp_path / "vault" / "vlmc_af_nsr" / "features" / "choi2024machine.md"
    note.write_text("my annotations")

    r = send(cfg, "choi2024machine", "features")

    assert note.read_text() == "my annotations"
    assert r["pdf_status"] == r["note_status"] == "exists"


@pytest.mark.parametrize("subtopic", ["../escape", "a/b", ".hidden", ""])
def test_send_rejects_subtopic_outside_vault(tmp_path, subtopic):
    cfg = _setup(tmp_path)
    with pytest.raises(VaultError):
        send(cfg, "choi2024machine", subtopic)


def test_send_unknown_paper(tmp_path):
    cfg = _setup(tmp_path)
    with pytest.raises(VaultError, match="no PDF"):
        send(cfg, "nope2020x", "features")


def test_index_not_duplicated_when_folder_already_embeds_table(tmp_path):
    cfg = _setup(tmp_path)
    folder = tmp_path / "vault" / "vlmc_af_nsr" / "features"
    folder.mkdir(parents=True)
    (folder / "Lista.md").write_text("![[Leitura.base#Desta pasta]]")
    send(cfg, "choi2024machine", "features")
    assert not (folder / "00 Papers.md").exists()

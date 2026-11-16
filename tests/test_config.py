import os
from pathlib import Path

from alcove.config import load_config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ALCOVE_DATA_DIR", str(tmp_path / "data"))
    cfg = load_config(tmp_path / "none.toml")
    assert cfg.port == 4545
    assert cfg.books_dirs == []


def test_reads_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("ALCOVE_DATA_DIR", str(tmp_path / "data"))
    f = tmp_path / "config.toml"
    f.write_text('books_dirs = ["~/Books"]\nport = 5000\n')
    cfg = load_config(f)
    assert cfg.books_dirs == [Path.home() / "Books"]
    assert cfg.port == 5000


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("ALCOVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALCOVE_BOOKS_DIRS", f"/a{os.pathsep}/b")
    monkeypatch.setenv("ALCOVE_PORT", "4600")
    cfg = load_config(tmp_path / "none.toml")
    assert cfg.books_dirs == [Path("/a"), Path("/b")]
    assert cfg.port == 4600
    assert cfg.data_dir == tmp_path / "data"


def test_secret_key_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("ALCOVE_DATA_DIR", str(tmp_path / "data"))
    a = load_config(tmp_path / "none.toml")
    b = load_config(tmp_path / "none.toml")
    assert a.secret_key and a.secret_key == b.secret_key

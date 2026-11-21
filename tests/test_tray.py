"""The Windows tray (packaging/windows/tray.py): the parts that aren't Windows itself."""

import importlib.util
from pathlib import Path

import pytest

from loft import updates

TRAY = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "tray.py"


@pytest.fixture
def tray(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("loft_tray", TRAY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(module, "DATA", tmp_path / "data")
    monkeypatch.setattr(module, "CONFIG", tmp_path / "data" / "config.toml")
    monkeypatch.setattr(module, "LOG", tmp_path / "data" / "server.log")
    monkeypatch.delenv("LOFT_PORT", raising=False)
    (tmp_path / "app").mkdir()
    return module


def test_it_agrees_with_the_server_on_the_update_exit_code(tray):
    assert tray.UPDATING == updates.UPDATING
    assert updates.TRAY == "Loft Server.exe"


@pytest.mark.parametrize("code, quitting, crashes, answers, what", [
    (0, True, 0, False, "nothing"),           # Quit or Restart from the menu
    (updates.UPDATING, False, 0, False, "quit"),   # stopped to be updated: let go of the files
    (1, False, 0, True, "leave"),              # another Loft has the port
    (1, False, 0, False, "restart"),
    (1, False, 4, False, "restart"),
    (1, False, 5, False, "give up"),
])
def test_what_happens_when_the_server_stops(tray, code, quitting, crashes, answers, what):
    assert tray.after_exit(code, quitting, crashes, answers) == what


def test_the_port_comes_from_config_then_the_environment(tray, monkeypatch):
    assert tray.port() == 4545
    tray.DATA.mkdir()
    tray.CONFIG.write_text("port = 5000\n")
    assert tray.port() == 5000
    monkeypatch.setenv("LOFT_PORT", "6000")
    assert tray.port() == 6000
    tray.CONFIG.write_text("port = [broken\n")
    monkeypatch.delenv("LOFT_PORT")
    assert tray.port() == 4545


def test_a_config_left_in_the_program_folder_comes_along(tray):
    (tray.APP_DIR / "config.toml").write_text("port = 5000\n")
    tray.prepare_data()
    assert tray.CONFIG.read_text() == "port = 5000\n"
    (tray.APP_DIR / "config.toml").write_text("port = 7000\n")
    tray.prepare_data()
    assert tray.CONFIG.read_text() == "port = 5000\n"   # never over one already there


def test_a_long_log_is_set_aside(tray):
    tray.DATA.mkdir()
    tray.LOG.write_bytes(b"x" * (tray.MAX_LOG + 1))
    tray.prepare_data()
    assert not tray.LOG.exists() and tray.LOG.with_name("server.log.1").stat().st_size == tray.MAX_LOG + 1

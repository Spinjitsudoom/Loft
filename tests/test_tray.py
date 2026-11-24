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


class FakeRegistry:
    """Just enough of winreg for Start with Windows, with the Run key missing at first (as on a
    new Windows profile)."""
    HKEY_CURRENT_USER, KEY_SET_VALUE, KEY_READ, REG_SZ = "HKCU", 2, 1, 1

    def __init__(self):
        self.keys: dict[str, dict] = {}

    class _Key:
        def __init__(self, values): self.values = values
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def OpenKey(self, root, path, reserved=0, access=1):
        if path not in self.keys:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return self._Key(self.keys[path])

    def CreateKeyEx(self, root, path, reserved=0, access=1):
        return self._Key(self.keys.setdefault(path, {}))

    def SetValueEx(self, key, name, reserved, kind, value): key.values[name] = value
    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(2, "no value")
        return key.values[name], self.REG_SZ
    def DeleteValue(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(2, "no value")
        del key.values[name]


def test_start_with_windows_works_when_the_run_key_is_missing(tray, monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setitem(__import__("sys").modules, "winreg", registry)
    assert not tray.autostart()
    tray.set_autostart(True)
    assert tray.autostart()
    assert registry.keys[tray.RUN_KEY][tray.RUN_NAME].endswith('" --background')
    tray.set_autostart(False)
    assert not tray.autostart()
    tray.set_autostart(False)   # already off: nothing to do


def test_restart_from_the_menu_starts_one_server(tray, monkeypatch):
    # The watcher of the stopped server can wake after Restart has already cleared "quitting":
    # it mustn't take the stop for a crash and start a second server beside the new one.
    import threading
    import types
    started, release = [], threading.Event()

    class Proc:
        def __init__(self):
            self.done = threading.Event()
        def wait(self, timeout=None):
            if timeout is None:          # the watcher: held until Restart is starting the new server,
                release.wait(5)          # and only ever wakes for a server that was stopped
                self.done.wait()
            return 1
        def poll(self):
            return 1 if self.done.is_set() else None
        def terminate(self):
            self.done.set()

    def popen(*args, **kw):
        if started:                      # Restart starting the new server: the old watcher wakes now
            release.set()
            threading.Event().wait(0.3)
        started.append(Proc())
        return started[-1]

    monkeypatch.setattr(tray, "subprocess", types.SimpleNamespace(Popen=popen, CREATE_NO_WINDOW=0, STDOUT=-2,
                                                                  DEVNULL=-3, TimeoutExpired=TimeoutError))
    monkeypatch.setattr(tray.time, "sleep", lambda s: None)
    monkeypatch.setattr(tray, "answering", lambda timeout=1.5: False)
    tray.DATA.mkdir(parents=True)
    server = tray.Server(on_update=lambda: None, on_trouble=lambda what: None)
    server.start()
    server.restart()
    threading.Event().wait(0.3)
    assert len(started) == 2 and server.proc is started[1] and server.crashes == 0

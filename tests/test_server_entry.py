"""packaging/server_entry.py: on Windows, loft-server.exe started by hand hands over to the tray."""

import importlib.util
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parent.parent / "packaging" / "server_entry.py"


@pytest.fixture
def entry():
    spec = importlib.util.spec_from_file_location("loft_server_entry", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("platform, env, argv, consoles, hand_over", [
    ("win32", {}, ["loft-server.exe"], 1, True),                         # double-clicked, or an old shortcut
    ("win32", {"LOFT_TRAY_PID": "42"}, ["loft-server.exe"], 1, False),   # the tray started it, hidden
    ("win32", {}, ["loft-server.exe"], 2, False),                        # typed in a terminal
    ("win32", {}, ["loft-server.exe", "--help"], 1, False),              # asked for something
    ("linux", {}, ["loft-server"], 1, False),
])
def test_who_hands_over_to_the_tray(entry, platform, env, argv, consoles, hand_over):
    assert entry.started_by_hand(platform, env, argv, consoles) is hand_over

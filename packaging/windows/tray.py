"""Loft Server for Windows: runs the Loft server in the background, with an icon in the
notification area (the tray) to open Loft, start it with Windows, update it, or stop it.

It's the program people start ("Loft Server.exe"). The server itself is the separate
loft-server.exe next to it, started without a window; what it says goes to
%LOCALAPPDATA%\\Loft\\server.log. Settings (config.toml) and the library live in %LOCALAPPDATA%\\Loft.

packaging/windows/loft-server.spec builds it; tests/test_tray.py tests the parts that aren't Windows.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(sys.executable).parent
BUNDLE = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Loft"
CONFIG = DATA / "config.toml"
LOG = DATA / "server.log"
SERVER = APP_DIR / "loft-server.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Loft Server"
UPDATING = 75          # loft-server's exit code when it stops to be updated (src/loft/updates.py)
MAX_LOG = 5_000_000
CRASHES = 5


def port() -> int:
    if os.environ.get("LOFT_PORT", "").isdigit():
        return int(os.environ["LOFT_PORT"])
    try:
        return int(tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("port", 4545))
    except (OSError, ValueError):
        return 4545


def answering(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port()}/api/ping", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def lan_address() -> str:
    """This computer's address on the local network, for phones and other computers."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; it just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def open_loft() -> None:
    webbrowser.open(f"http://localhost:{port()}/")


def prepare_data() -> None:
    """Make the data folder; bring along a config.toml left in the program's folder (the first
    0.1.3 setup started Loft from there); keep the log from growing without end."""
    DATA.mkdir(parents=True, exist_ok=True)
    old = APP_DIR / "config.toml"
    if old.is_file() and not CONFIG.exists():
        shutil.copy2(old, CONFIG)
    try:
        if LOG.stat().st_size > MAX_LOG:
            LOG.replace(LOG.with_name("server.log.1"))
    except OSError:
        pass


def after_exit(code: int, quitting: bool, crashes: int, someone_answers: bool) -> str:
    """What to do when the server stops: "nothing" (it was asked to), "quit" (it's being
    updated: let go of the files), "leave" (another Loft already answers on that port),
    "restart", or "give up" (it keeps failing)."""
    if quitting:
        return "nothing"
    if code == UPDATING:
        return "quit"
    if someone_answers:
        return "leave"
    return "restart" if crashes < CRASHES else "give up"


# ---------- Windows only ----------

def first_instance() -> bool:
    """Only one tray per person: a second start just opens Loft."""
    import ctypes
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LoftServerTray")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def autostart() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


class Server:
    def __init__(self, on_update, on_trouble) -> None:
        self.proc: subprocess.Popen | None = None
        self.quitting = False
        self.crashes = 0
        self.on_update, self.on_trouble = on_update, on_trouble

    def start(self) -> None:
        env = {**os.environ, "LOFT_CONFIG": str(CONFIG), "LOFT_TRAY_PID": str(os.getpid())}
        log = open(LOG, "ab", buffering=0)
        self.proc = subprocess.Popen([str(SERVER)], cwd=DATA, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True).start()

    def _watch(self, proc: subprocess.Popen) -> None:
        code = proc.wait()
        if proc is not self.proc:
            return
        what = after_exit(code, self.quitting, self.crashes, not self.quitting and answering())
        if what == "quit":
            self.on_update()
        elif what == "restart":
            self.crashes += 1
            time.sleep(3)
            self.start()
        elif what in ("leave", "give up"):
            self.on_trouble(what)

    def stop(self) -> None:
        self.quitting = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def restart(self) -> None:
        self.stop()
        self.quitting = False
        self.crashes = 0
        self.start()


def self_test() -> int:
    """For the build: everything the tray needs is in the package. Exit code 0 if so."""
    import pystray  # noqa: F401
    from PIL import Image
    Image.open(BUNDLE / "icon.png").load()
    return 0 if SERVER.exists() else 1


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    background = "--background" in sys.argv
    if not first_instance() or answering():  # already running: just open it
        if not background:
            open_loft()
        return

    import pystray
    from PIL import Image

    from loft import updates
    from loft.config import load_config

    prepare_data()
    first = not (DATA / ".tray").exists()
    if first:
        set_autostart(True)  # a server is for having on: the menu turns this off
        (DATA / ".tray").write_text("Loft Server has been started here before.\n")

    update_to: list[str] = []   # set when the person chooses Update: installed after the tray closes

    def notify(text: str) -> None:
        try:
            icon.notify(text, "Loft Server")
        except Exception:
            pass

    def trouble(what: str) -> None:
        notify("Another Loft is already running on this port." if what == "leave"
               else f"Loft stopped and couldn’t start again. What it said is in {LOG}.")

    cfg = load_config(CONFIG)  # before the server starts: the first time, this makes the key sign-ins use
    server = Server(on_update=lambda: icon.stop(), on_trouble=trouble)
    server.start()

    def when_ready() -> None:
        for _ in range(120):
            if answering():
                if not background:
                    open_loft()  # the first time, Loft asks for a name and password for the admin
                return
            time.sleep(0.5)

    threading.Thread(target=when_ready, daemon=True).start()

    # New versions: the server downloads them; the tray says so and offers to install.
    ready: dict = {"version": ""}

    def watch_updates() -> None:
        told = set()
        time.sleep(90)
        while True:
            try:
                now = updates.status(cfg)
                ready["version"] = now["latest"] if now["ready"] else ""
                if ready["version"] and ready["version"] not in told:
                    told.add(ready["version"])
                    icon.update_menu()
                    notify(f"Loft {ready['version']} is ready. Choose “Update” in the Loft Server menu.")
            except Exception:
                pass
            time.sleep(600)

    def update_now(icon, _item) -> None:
        update_to.append(ready["version"])
        server.stop()
        icon.stop()

    def quit_all(icon, _item) -> None:
        server.stop()
        icon.stop()

    icon = pystray.Icon(
        "loft",
        Image.open(BUNDLE / "icon.png"),
        "Loft Server",
        menu=pystray.Menu(
            pystray.MenuItem("Open Loft", lambda *_: open_loft(), default=True),
            pystray.MenuItem(lambda _i: f"On other devices: {lan_address()}:{port()}", None, enabled=False),
            pystray.MenuItem(lambda _i: f"Update to Loft {ready['version']}", update_now,
                             visible=lambda _i: bool(ready["version"])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start with Windows", lambda *_: set_autostart(not autostart()),
                             checked=lambda _i: autostart()),
            pystray.MenuItem("Open the data folder", lambda *_: os.startfile(DATA)),
            pystray.MenuItem("Restart the server", lambda *_: server.restart()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Loft Server", quit_all),
        ),
    )
    threading.Thread(target=watch_updates, daemon=True).start()
    icon.run()
    if update_to:
        updates._restart_into(update_to[0])  # swaps in the new version, starts this tray again, exits


if __name__ == "__main__":
    main()

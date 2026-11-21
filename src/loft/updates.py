"""Keeping Loft up to date.

Once a day (while the admin leaves "Check for new versions" on) the server asks GitHub for Loft's
newest release. The standalone server (packaging/build_server.py) then downloads the copy built
for this system, checks it against the release's SHA256SUMS.txt, unpacks it next to itself, and
tells the admins it's ready. Nothing changes until an admin chooses Restart to update: then the
new folder takes the old one's place (the old one is kept beside it as "<name>.previous") and
Loft starts again from it. On Windows a copy installed with the setup is updated by the next setup
instead, run silently, so Windows' list of installed apps stays right. Loft installed any other way (Docker, from source) is only told a new
version is out, since it's updated the way it was installed.

Only Loft's own release address is asked, and nothing about the library is sent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .config import Config
from .db import session

log = logging.getLogger(__name__)

REPO = "Spinjitsudoom/Loft"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/")
KEY = "updates"                 # what's known about the newest release, in the meta table
EVERY = 24 * 3600               # how often to ask
TIMEOUT = 30
MAX_JSON = 2_000_000
MAX_ARCHIVE = 400_000_000
PROGRAM = "loft-server.exe" if sys.platform == "win32" else "loft-server"
TRAY = "Loft Server.exe"        # on Windows, what runs the server hidden (packaging/windows/tray.py)
UPDATING = 75                   # the exit code that tells the tray the server stopped to be updated
VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,6})$")

_lock = threading.Lock()        # one check or download at a time


def latest_url() -> str:
    # LOFT_UPDATES_URL lets the tests stand in for GitHub.
    return os.environ.get("LOFT_UPDATES_URL") or LATEST


def current_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("loft")
    except PackageNotFoundError:
        return "0.0.0"


def parse(text: str) -> tuple[int, int, int] | None:
    m = VERSION.match(str(text or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def newer(candidate: str, than: str) -> bool:
    a, b = parse(candidate), parse(than)
    return bool(a and b and a > b)


def system() -> tuple[str, str]:
    name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return name, arch


def asset_name(version: str) -> str:
    name, arch = system()
    if by_setup():
        return f"loft-server-{version}-{name}-{arch}-setup.exe"
    return f"loft-server-{version}-{name}-{arch}.{'tar.gz' if name == 'linux' else 'zip'}"


def install_dir() -> Path | None:
    """The standalone server's folder, or None when Loft runs some other way."""
    if not getattr(sys, "frozen", False) and not os.environ.get("LOFT_UPDATES_INSTALL"):
        return None
    return Path(os.environ.get("LOFT_UPDATES_INSTALL") or Path(sys.executable).parent).resolve()


def by_setup() -> bool:
    """Whether this copy was installed on Windows with the setup (which leaves its uninstaller here)."""
    home = install_dir()
    return bool(sys.platform == "win32" and home and (home / "unins000.exe").is_file())


def can_install() -> bool:
    """Whether this copy can replace itself: it's the standalone server and may write beside itself."""
    home = install_dir()
    return bool(home and os.access(home, os.W_OK) and os.access(home.parent, os.W_OK))


def staging_dir(version: str) -> Path:
    home = install_dir()
    return home.parent / f".{home.name}.update-{version}"


def _staged(version: str) -> Path:
    """What a finished download leaves: the next setup, or the new server unpacked."""
    stage = staging_dir(version)
    return stage / asset_name(version) if by_setup() else stage / PROGRAM


# ---------- what's known ----------

def _load(cfg: Config) -> dict:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (KEY,)).fetchone()
    try:
        value = json.loads(row["value"]) if row else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _save(cfg: Config, **changes) -> dict:
    state = {**_load(cfg), **changes}
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (KEY, json.dumps(state)))
    return state


def status(cfg: Config) -> dict:
    state = _load(cfg)
    current = current_version()
    latest = state.get("latest") or ""
    is_newer = newer(latest, current)
    ready = bool(is_newer and state.get("ready") == latest and can_install() and _staged(latest).is_file())
    return {
        "current": current,
        "latest": latest if is_newer else current,
        "newer": is_newer,
        "notes_url": state.get("notes_url", "") if is_newer else "",
        "can_install": can_install(),
        "downloading": bool(is_newer and state.get("downloading")),
        "ready": ready,
        "checked_at": state.get("checked_at"),
        "error": state.get("error", ""),
    }


# ---------- asking and downloading ----------

def _get(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"Loft/{current_version()} (update check)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too big")
    return data


def _download(url: str, to: Path) -> None:
    if not (url.startswith(DOWNLOAD_HOSTS) or os.environ.get("LOFT_UPDATES_URL")):
        raise ValueError("unexpected download address")
    request = urllib.request.Request(url, headers={"User-Agent": f"Loft/{current_version()} (update)"})
    size = 0
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, to.open("wb") as out:
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > MAX_ARCHIVE:
                raise ValueError("download too big")
            out.write(chunk)


def _sums(text: str) -> dict[str, str]:
    """SHA256SUMS.txt: "<hash>  <name>" per line."""
    found = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            found[parts[1].lstrip("*")] = parts[0]
    return found


def check(cfg: Config, download: bool = True) -> dict:
    """Ask for the newest release; when it's newer and this copy can install it, fetch it too."""
    with _lock:
        try:
            release = json.loads(_get(latest_url(), MAX_JSON))
            version = str(release.get("tag_name", "")).lstrip("v")
            if release.get("draft") or release.get("prerelease") or not parse(version):
                raise ValueError("no usable release")
            assets = {a.get("name"): a.get("browser_download_url", "") for a in release.get("assets") or []
                      if isinstance(a, dict)}
            state = _save(cfg, checked_at=time.time(), latest=version, error="",
                          notes_url=str(release.get("html_url", "")), assets=assets)
        except Exception as e:  # offline, GitHub busy: try again tomorrow
            log.info("Update check failed: %s", e)
            _save(cfg, checked_at=time.time(), error="Loft couldn’t reach GitHub to check for a new version.")
            return status(cfg)

        current = current_version()
        if not newer(version, current):
            return status(cfg)
        if download and can_install() and state.get("ready") != version:
            _save(cfg, downloading=True)
            try:
                _fetch(version, state["assets"])
                _save(cfg, ready=version, downloading=False)
            except Exception as e:
                log.warning("Downloading Loft %s failed: %s", version, e)
                _save(cfg, downloading=False, error=f"Loft {version} couldn’t be downloaded; it will try again later.")
        if download or not can_install():  # otherwise the download that follows tells them
            _tell_admins(cfg, version)
        return status(cfg)


def _fetch(version: str, assets: dict[str, str]) -> None:
    name = asset_name(version)
    if name not in assets or "SHA256SUMS.txt" not in assets:
        raise ValueError(f"the release has no {name}")
    expected = _sums(_get(assets["SHA256SUMS.txt"], MAX_JSON).decode("utf-8", "replace")).get(name)
    if not expected:
        raise ValueError(f"SHA256SUMS.txt doesn't list {name}")
    stage = staging_dir(version)
    for old in stage.parent.glob(f".{install_dir().name}.update-*"):  # an earlier download nobody installed
        shutil.rmtree(old, ignore_errors=True)
    stage.mkdir(parents=True)
    archive = stage / name
    try:
        _download(assets[name], archive)
        digest = hashlib.sha256()
        with archive.open("rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("the download doesn't match its checksum")
        if by_setup():
            return  # the setup itself is what's run
        unpacked = stage / "unpacked"
        unpack(archive, unpacked)
        archive.unlink()
        top = [p for p in unpacked.iterdir()]
        root = top[0] if len(top) == 1 and top[0].is_dir() else unpacked
        if not (root / PROGRAM).is_file():
            raise ValueError("the download has no server in it")
        for item in root.iterdir():
            item.rename(stage / item.name)
        shutil.rmtree(unpacked)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def unpack(archive: Path, into: Path) -> None:
    """Unpack a release archive, keeping execute bits and symlinks (macOS needs both) but never
    writing outside `into`."""
    into.mkdir(parents=True, exist_ok=True)
    base = into.resolve()
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tar:
            tar.extractall(into, filter="data")
        return
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = (into / info.filename).resolve()
            if target != base and base not in target.parents:
                raise ValueError("unsafe path in the download")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                link = z.read(info).decode()
                if os.path.isabs(link) or base not in (target.parent / link).resolve().parents:
                    raise ValueError("unsafe link in the download")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(link, target)
            elif info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                if mode & 0o777:
                    target.chmod(mode & 0o755)


def _tell_admins(cfg: Config, version: str) -> None:
    """Once per version: "ready to install" when it can be, else "is out"."""
    from .notifications import admins, notify
    state = _load(cfg)
    ready = status(cfg)["ready"]
    said = state.get("told") or {}
    kind = "ready" if ready else "out"
    if said.get(version) in (kind, "ready"):
        return
    text = (f"Loft {version} is ready to install: restart to update in Library settings" if ready
            else f"Loft {version} is out")
    with session(cfg.db_path) as con:
        notify(con, admins(con), "update", text, "#/admin")
    _save(cfg, told={**said, version: kind})


# ---------- installing ----------

def install(cfg: Config) -> str:
    """Swap the downloaded version in and start it. Returns the version; the restart happens a
    moment later, so the answer reaches the admin first. Raises LookupError when nothing is ready."""
    now = status(cfg)
    if not now["ready"]:
        raise LookupError("No new version is downloaded and ready")
    version = now["latest"]
    threading.Timer(0.5, _restart_into, (version,)).start()
    return version


def _restart_into(version: str) -> None:
    home, stage = install_dir(), staging_dir(version)
    previous = home.with_name(home.name + ".previous")
    argv = [str(home / PROGRAM), *sys.argv[1:]]
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    log.warning("Restarting into Loft %s", version)
    if sys.platform == "win32":
        _restart_windows(home, stage, previous, argv, env, setup=_staged(version) if by_setup() else None)
        return
    try:
        shutil.rmtree(previous, ignore_errors=True)
        here = Path.cwd().resolve() == home
        home.rename(previous)
        stage.rename(home)
        if (previous / "config.toml").is_file() and not (home / "config.toml").exists():
            shutil.copy2(previous / "config.toml", home / "config.toml")
        if here:
            os.chdir(home)
    except Exception:
        log.exception("Couldn’t put Loft %s in place", version)
        if not home.exists() and previous.exists():
            previous.rename(home)
        return
    os.execve(argv[0], argv, env)


def _restart_windows(home: Path, stage: Path, previous: Path, argv: list[str], env: dict,
                     setup: Path | None = None) -> None:
    # A running program's folder can't be moved on Windows: a small script waits for Loft to
    # stop, swaps the folders (or runs the next setup, for a copy the setup installed) and starts
    # the new one in a window of its own.
    script = home.parent / f".{home.name}.update.cmd"
    args = subprocess.list2cmdline(argv[1:])
    here = Path.cwd().resolve()
    cwd = home if here == home else here
    # Run by the tray (or the tray itself updating): wait for it too, and start it again after.
    tray_pid = os.environ.get("LOFT_TRAY_PID", "")
    by_tray = (home / TRAY).is_file() and (tray_pid.isdigit() or Path(sys.executable).name == TRAY)
    pids = [str(os.getpid())] + ([tray_pid] if tray_pid.isdigit() else [])
    if by_tray:
        start = f'start "" /D "{home}" "{home / TRAY}" --background'
    else:
        start = f'start "Loft" /D "{cwd}" "{home / PROGRAM}" {args}'
    if setup:
        replace = [
            f'start "" /wait "{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-',
            f'rmdir /s /q "{stage}" 2>nul',
        ]
    else:
        replace = [
            f'rmdir /s /q "{previous}" 2>nul',
            f'move "{home}" "{previous}" >nul || goto start',
            f'move "{stage}" "{home}" >nul || move "{previous}" "{home}" >nul',
            f'if exist "{previous}\\config.toml" if not exist "{home}\\config.toml" copy /y "{previous}\\config.toml" "{home}\\" >nul',
        ]
    script.write_text("\r\n".join([
        "@echo off",
        ":wait",
        *[f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)' for pid in pids],
        *replace,
        ":start",
        start,
        '(goto) 2>nul & del "%~f0"',
    ]) + "\r\n")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    env = {k: v for k, v in env.items() if k != "LOFT_TRAY_PID"}
    subprocess.Popen(["cmd", "/c", str(script)], env=env, creationflags=flags, close_fds=True, cwd=str(home.parent))
    os._exit(UPDATING)


# ---------- the daily check ----------

class UpdateChecker:
    """Checks a minute after starting, then once a day, while the admin allows it."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="loft-updates", daemon=True)
            self._thread.start()

    def trigger(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        self._wake.wait(timeout=60)
        while True:
            self._wake.clear()
            try:
                from .libsettings import get_library
                due = time.time() - (_load(self.cfg).get("checked_at") or 0) > EVERY
                if get_library(self.cfg)["check_updates"] and due:
                    check(self.cfg)
            except Exception:
                log.exception("Update check failed")
            self._wake.wait(timeout=3600)

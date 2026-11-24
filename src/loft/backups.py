"""Backups of the library: what a rescan can't rebuild.

A backup is one zip, loft-YYYY-MM-DD-HHMMSS.zip, holding the database (accounts, reading progress,
shelves, bookmarks, edits, filled-in details, library settings), covers/ (covers chosen by hand
exist only there) and uploads/ (books sent but not yet approved). Not the page and flow caches,
which Loft remakes, and not secret_key: a backup file must not be enough to sign in as anyone.

The admin chooses how often (every day, every week, or off), where (the data folder's backups/
until another folder is picked: another drive is safer) and how many to keep (a week of daily
backups then one a week for eight weeks, or the newest 5, 10 or 30). The database is copied with
SQLite's online backup, so it's whole even while Loft is busy, and each zip is written under a
temporary name and renamed when it's complete. Only files named like Loft's backups are ever
listed, removed or restored, so the folder can be shared with other things.

Carried over from Shelf's backups.py (the user's music server).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import json
import tempfile
import threading
import time
import zipfile
from datetime import date
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

DAY = 86400
RESTORE_SUFFIX = "-before-restore"
SAFETY_DAYS = 30   # how long the backup made before a restore is kept
# loft-<when>-<which Loft made it>[-before-restore].zip
NAME = re.compile(r"loft-(\d{4}-\d{2}-\d{2}-\d{6})-([0-9a-f]{6})(-before-restore)?\.zip")
STAMP = "%Y-%m-%d-%H%M%S"
MARKER = ".loft-backups"   # in a folder the admin chose: its drive is there (not an empty mount point)
EVERY = {"day": DAY - 3600, "week": 7 * DAY - 3600}   # a little under, so it doesn't creep later
FOLDERS = ("covers", "uploads")   # beside loft.db in each backup
KEPT_SETTINGS = ("backup_every", "backup_dir", "backup_keep")   # not put back by a restore

_lock = threading.Lock()


class BackupError(Exception):
    """Something about a backup, said so an admin can act on it."""


def _settings(cfg: Config) -> dict:
    from .libsettings import get_library
    return get_library(cfg)


def server_id(cfg: Config) -> str:
    """Which Loft made a backup, so two sharing a folder leave each other's alone. From this
    server's own secret (never the secret itself); a new install is a new Loft."""
    return hashlib.sha256(f"loft-backups:{cfg.secret_key}".encode()).hexdigest()[:6]


def folder(cfg: Config) -> Path:
    chosen = _settings(cfg)["backup_dir"]
    return Path(chosen) if chosen else cfg.data_dir / "backups"


def _source(cfg: Config, name: str) -> Path:
    return cfg.cover_dir if name == "covers" else cfg.data_dir / name


def due(times: list[float], now: float, every: str) -> bool:
    """Whether a backup is due: none yet, or the newest is about a day (or a week) old."""
    if every not in EVERY:
        return False
    return not times or now - max(times) >= EVERY[every]


def to_keep(times: list[float], now: float, keep: int) -> set[float]:
    """Which backups to keep, by when they were made. keep = 0: the newest of each of the last 7
    days, then of each of the 8 weeks before. Otherwise the newest `keep`. The newest is always kept.

    Days and weeks are fixed on the calendar, not counted back from now: counted back, the places
    move every hour, and each day's backup would push the one before it out of the first week's
    place before it could reach the next."""
    if not times:
        return set()
    if keep:
        return set(sorted(times)[-keep:])
    today = date.fromtimestamp(now).toordinal()
    last_week = (today - 7) // 7              # the week holding the day before the last seven
    newest_in: dict[tuple[str, int], float] = {}
    for t in times:
        day = date.fromtimestamp(t).toordinal()
        if today - day < 7:
            slot = ("day", day)
        elif last_week - day // 7 < 8:
            slot = ("week", day // 7)
        else:
            continue
        newest_in[slot] = max(newest_in.get(slot, t), t)
    return {max(times)} | set(newest_in.values())


def _when(p: Path) -> float:
    """When a backup was made: from its name, which copying doesn't change (its file date does)."""
    m = NAME.fullmatch(p.name)
    try:
        return time.mktime(time.strptime(m.group(1), STAMP))
    except (AttributeError, ValueError, OverflowError):
        return p.stat().st_mtime


def _files(cfg: Config) -> list[tuple[Path, float]]:
    """Loft's backups in the folder, oldest first, with when each was made."""
    d = folder(cfg)
    if not d.is_dir():
        return []
    found = [(p, _when(p)) for p in d.iterdir() if NAME.fullmatch(p.name) and p.is_file()]
    return sorted(found, key=lambda pt: pt[1])


def _is_safety(p: Path) -> bool:
    return p.name.endswith(RESTORE_SUFFIX + ".zip")


def _mine(cfg: Config, p: Path) -> bool:
    return NAME.fullmatch(p.name).group(2) == server_id(cfg)


def list_backups(cfg: Config) -> list[dict]:
    """Newest first. `mine` is false for one another Loft made in the same folder."""
    return [{"name": p.name, "at": at, "size": p.stat().st_size, "before_restore": _is_safety(p),
             "mine": _mine(cfg, p)} for p, at in reversed(_files(cfg))]


def _ready(cfg: Config) -> Path:
    """The folder to write to, made if it's Loft's own. A folder the admin chose is never made, and
    must have the mark left when it was chosen: if its drive isn't there, the folder (or an empty
    mount point) would put backups on whatever disk is there instead."""
    d = folder(cfg)
    if _settings(cfg)["backup_dir"]:
        if not d.is_dir():
            raise FileNotFoundError(2, "The backup folder isn’t there (is its drive connected?)", str(d))
        if not (d / MARKER).is_file():
            raise FileNotFoundError(2, "The backup folder’s drive doesn’t seem to be connected "
                                       "(choose the folder again if it is)", str(d))
    else:
        d.mkdir(parents=True, exist_ok=True)
    return d


def mark(d: Path) -> None:
    """Leave the mark in a folder the admin chose (see _ready)."""
    (d / MARKER).write_text("Loft keeps its backups here. Leave this file: it tells Loft the drive is connected.\n")


def make(cfg: Config, now: float | None = None, suffix: str = "") -> Path:
    """Back up the library now. Returns the zip made. Raises OSError when it can't be written."""
    now = time.time() if now is None else now
    d = _ready(cfg)
    out = d / f"loft-{time.strftime(STAMP, time.localtime(now))}-{server_id(cfg)}{suffix}.zip"
    part = out.with_name(out.name + ".part")
    with _lock, tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "loft.db"
        src, dst = sqlite3.connect(cfg.db_path, timeout=30), sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        try:
            with zipfile.ZipFile(part, "w") as z:
                z.write(copy, "loft.db", compress_type=zipfile.ZIP_DEFLATED)
                for name in FOLDERS:
                    base = _source(cfg, name)
                    if not base.is_dir():
                        continue
                    for f in sorted(p for p in base.rglob("*") if p.is_file()):
                        # Covers and books are already compressed: stored as they are.
                        z.write(f, f"{name}/{f.relative_to(base).as_posix()}", compress_type=zipfile.ZIP_STORED)
            part.replace(out)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    os.utime(out, (now, now))
    log.info("Backed up the library to %s", out)
    if not suffix:
        prune(cfg, now)
    return out


def prune(cfg: Config, now: float | None = None) -> int:
    """Remove this Loft's backups the admin's choice doesn't keep. Nothing while backups are off,
    and never another Loft's."""
    now = time.time() if now is None else now
    settings = _settings(cfg)
    if settings["backup_every"] == "off":
        return 0
    files = [(p, at) for p, at in _files(cfg) if _mine(cfg, p)]
    keep = to_keep([at for p, at in files if not _is_safety(p)], now, settings["backup_keep"])
    gone = 0
    for p, at in files:
        if (now - at > SAFETY_DAYS * DAY) if _is_safety(p) else at not in keep:
            p.unlink(missing_ok=True)
            gone += 1
    return gone


def path_of(cfg: Config, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise BackupError("That isn’t one of Loft’s backups")
    p = folder(cfg) / name
    if not p.is_file():
        raise BackupError("That backup isn’t there any more")
    return p


# ---------- restoring ----------

def _member_ok(name: str) -> bool:
    """Only what a backup holds, and nothing that could land outside the data folder."""
    parts = name.split("/")
    if name.startswith("/") or "\\" in name or ":" in parts[0] or ".." in parts or "" in parts[:-1]:
        return False
    return name == "loft.db" or (parts[0] in FOLDERS and len(parts) > 1)


def _check_database(db: Path) -> None:
    try:
        con = sqlite3.connect(db)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise BackupError("That backup is damaged") from e
    if not ok:
        raise BackupError("That backup is damaged")
    if not {"users", "books"} <= tables:
        raise BackupError("That isn’t one of Loft’s backups")


def restore(cfg: Config, name: str) -> Path:
    """Put the library back as it was in a backup (this Loft's, or another's in the same folder).
    What's there now is backed up first (and that backup returned), so a wrong restore can be undone
    the same way. Nothing changes unless the backup is whole and Loft's, and nothing has changed if
    putting it back fails. Everyone signs in again afterwards."""
    import shutil

    from .db import session

    p = path_of(cfg, name)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cfg.data_dir, prefix=".restore-") as tmp:   # same drive: quick moves
        tmp = Path(tmp)
        try:
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
                if "loft.db" not in names or not all(_member_ok(n) for n in names):
                    raise BackupError("That isn’t one of Loft’s backups")
                z.extractall(tmp)   # reads every member, so a damaged one is found here
        except (zipfile.BadZipFile, EOFError, OSError, ValueError) as e:
            raise BackupError("That backup can’t be read") from e
        _check_database(tmp / "loft.db")

        try:
            safety = make(cfg, suffix=RESTORE_SUFFIX)
        except (OSError, sqlite3.Error) as e:
            raise BackupError(f"Loft couldn’t back up what’s there first, so nothing was changed: {_reason(e)}") from e
        settings = _settings(cfg)
        keep_settings = {k: settings[k] for k in KEPT_SETTINGS}
        with session(cfg.db_path) as con:
            newest_version = con.execute("SELECT COALESCE(MAX(version), 0) FROM users").fetchone()[0]
        with _lock:
            # The folders first, then the database: if anything fails (on Windows, a cover being
            # shown can't be moved), what was moved goes back and nothing has changed.
            moved: list[tuple[Path, Path, Path]] = []
            try:
                for folder_name in FOLDERS:
                    live, restored = _source(cfg, folder_name), tmp / folder_name
                    aside = tmp / f"replaced-{folder_name}"
                    if live.exists():
                        live.rename(aside)
                    moved.append((live, aside, restored))
                    if restored.is_dir():
                        restored.rename(live)
                    else:
                        live.mkdir(parents=True, exist_ok=True)
                src, dst = sqlite3.connect(tmp / "loft.db"), sqlite3.connect(cfg.db_path, timeout=30)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
            except (OSError, sqlite3.Error) as e:
                for live, aside, _ in reversed(moved):
                    try:
                        if live.exists():
                            shutil.rmtree(live)
                        if aside.exists():
                            aside.rename(live)
                    except OSError:
                        log.exception("Couldn’t put %s back after a failed restore (it's in %s)", live, aside)
                raise BackupError(f"The library couldn’t be put back, so nothing was changed: {_reason(e)}. "
                                  "Try again in a moment.") from e
            # Pages and unpacked books are made from the files by book file id: start them afresh.
            for cache in (cfg.page_dir, cfg.flow_dir):
                shutil.rmtree(cache, ignore_errors=True)
    with session(cfg.db_path) as con:   # opening it adds any columns added since the backup was made
        # Everyone signs in again. A sign-in names an account by number and version, and a removed
        # account's number goes to the next person: after a restore, someone's sign-in could
        # otherwise become someone else's, and sign-outs since the backup would be undone.
        con.execute("UPDATE users SET version = version + ?", (newest_version + 1,))
        # The backup settings stay as they are now: they say where the backups are, including the one
        # just made of what was there.
        row = con.execute("SELECT value FROM meta WHERE key = 'library'").fetchone()
        try:
            library = json.loads(row["value"]) if row else {}
        except ValueError:
            library = {}
        library = {**(library if isinstance(library, dict) else {}), **keep_settings}
        con.execute("INSERT INTO meta(key, value) VALUES ('library', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (json.dumps(library),))
    log.warning("Restored the library from %s (what was there is in %s)", name, safety.name)
    return safety


# ---------- by itself ----------

STATE = "backups"   # meta key: {"error": what went wrong last time, or "", "told": admins were told}


def _load(cfg: Config) -> dict:
    from .db import session
    with session(cfg.db_path) as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (STATE,)).fetchone()
    try:
        value = json.loads(row["value"]) if row else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _save(cfg: Config, **changes) -> None:
    from .db import session
    state = {**_load(cfg), **changes}
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (STATE, json.dumps(state)))


def _reason(e: Exception) -> str:
    reason = getattr(e, "strerror", None) or str(e) or type(e).__name__
    where = getattr(e, "filename", None)
    return reason + (f" ({where})" if where else "")


def _failed(cfg: Config, e: Exception) -> str:
    """Remember why, and tell the admins once until a backup works again."""
    from .db import session
    from .notifications import admins, notify
    text = f"Loft couldn’t back up the library: {_reason(e)}"
    log.warning("%s", text)
    told = _load(cfg).get("told")
    _save(cfg, error=text, told=True)
    if not told:
        with session(cfg.db_path) as con:
            notify(con, admins(con), "backup", text, "#/admin")
    return text


def make_now(cfg: Config, now: float | None = None) -> Path:
    """A backup the schedule (or Back up now) asked for: success clears an earlier error."""
    try:
        made = make(cfg, now)
    except (OSError, sqlite3.Error) as e:
        _failed(cfg, e)
        raise
    _save(cfg, error="", told=False)
    return made


def step(cfg: Config, now: float | None = None) -> Path | None:
    """Make a backup if one is due by the admin's schedule. Never raises: a failure is kept for the
    panel and told to the admins."""
    now = time.time() if now is None else now
    every = _settings(cfg)["backup_every"]
    try:
        regular = [b["at"] for b in list_backups(cfg) if b["mine"] and not b["before_restore"]]
    except OSError as e:   # a folder Loft can no longer look in
        _failed(cfg, e)
        return None
    if not due(regular, now, every):
        return None
    try:
        return make_now(cfg, now)
    except (OSError, sqlite3.Error):
        return None


def status(cfg: Config) -> dict:
    settings = _settings(cfg)
    error = _load(cfg).get("error", "")
    try:
        listed = list_backups(cfg)
    except OSError as e:   # Library settings must still open, saying why
        listed, error = [], f"Loft can’t look in the backup folder: {_reason(e)}"
    regular = [b["at"] for b in listed if b["mine"] and not b["before_restore"]]
    return {
        "every": settings["backup_every"],
        "keep": settings["backup_keep"],
        "folder": str(folder(cfg)),
        "folder_is_default": not settings["backup_dir"],
        "backups": listed,
        "last_at": max(regular) if regular else None,
        "error": error,
    }


class BackupKeeper:
    """Looks two minutes after Loft starts, then every hour, whether a backup is due."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="loft-backups", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        time.sleep(120)
        while True:
            try:
                step(self.cfg)
            except Exception:   # try again in an hour
                log.exception("Backing up the library failed")
            time.sleep(3600)

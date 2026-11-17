"""Library settings, set by the admin in the app: the library's name, the books folders, where
uploads go, how often to scan, whether plain-text files count as books, and online lookups.

Stored in the database (only what the admin changed). Until the admin saves a folder list, the one
from config.toml (or ALCOVE_BOOKS_DIRS) is used.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .config import Config
from .db import session

KEY = "library"
MAX_NAME = 40
MAX_FOLDERS = 10
SCAN_MINUTES = range(5, 1441)


def _stored(cfg: Config) -> dict:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (KEY,)).fetchone()
    try:
        value = json.loads(row["value"]) if row else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def get_library(cfg: Config) -> dict:
    stored = _stored(cfg)
    dirs = stored.get("books_dirs") or [str(d) for d in cfg.books_dirs]
    upload = stored.get("upload_dir")
    return {
        "name": stored.get("name", ""),
        "books_dirs": dirs,
        "upload_dir": upload if upload in dirs else (dirs[0] if dirs else ""),
        "scan_interval_minutes": stored.get("scan_interval_minutes", cfg.scan_interval_minutes),
        "allow_txt": stored.get("allow_txt", False),
        "online_lookups": stored.get("online_lookups", True),
    }


def books_dirs(cfg: Config) -> list[Path]:
    return [Path(d) for d in get_library(cfg)["books_dirs"]]


def allow_txt(cfg: Config) -> bool:
    return get_library(cfg)["allow_txt"]


def _folders(value) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FOLDERS:
        raise ValueError(f"books_dirs must list between 1 and {MAX_FOLDERS} folders")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("books_dirs: each folder must be a path")
        path = Path(item.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError(f"books_dirs: use the full path, starting from the top ({item})")
        if not path.is_dir():
            raise ValueError(f"books_dirs: Alcove can’t find a folder at {path}")
        if not os.access(path, os.R_OK | os.X_OK):
            raise ValueError(f"books_dirs: Alcove isn’t allowed to read {path}")
        if str(path) not in result:
            result.append(str(path))
    # A folder inside another (or the same folder by another path) would hold every book twice.
    real = [(p, Path(p).resolve()) for p in result]
    for i, (a, ra) in enumerate(real):
        for b, rb in real[i + 1:]:
            if ra == rb:
                raise ValueError(f"books_dirs: {a} and {b} are the same folder")
            if ra.is_relative_to(rb) or rb.is_relative_to(ra):
                inner, outer = (a, b) if ra.is_relative_to(rb) else (b, a)
                raise ValueError(f"books_dirs: {inner} is inside {outer}, which Alcove already looks through")
    return result


def _clean(patch: dict, current: dict) -> dict:
    clean: dict = {}
    for key, value in patch.items():
        if key == "name":
            if not isinstance(value, str):
                raise ValueError("name must be text")
            value = " ".join(value.split())
            if len(value) > MAX_NAME:
                raise ValueError(f"name can be at most {MAX_NAME} characters")
        elif key == "books_dirs":
            value = _folders(value)
        elif key == "upload_dir":
            if not isinstance(value, str):
                raise ValueError("upload_dir must be one of the books folders")
            value = str(Path(value.strip()).expanduser()) if value.strip() else ""
        elif key == "scan_interval_minutes":
            if not isinstance(value, int) or isinstance(value, bool) or value not in SCAN_MINUTES:
                raise ValueError(f"scan_interval_minutes must be between {SCAN_MINUTES.start} and {SCAN_MINUTES.stop - 1}")
        elif key in ("allow_txt", "online_lookups"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be on or off")
        else:
            raise ValueError(f"Unknown library setting {key}")
        clean[key] = value
    dirs = clean.get("books_dirs", current["books_dirs"])
    if "upload_dir" in clean and clean["upload_dir"] not in dirs:
        raise ValueError("upload_dir must be one of the books folders")
    return clean


def update_library(cfg: Config, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("Library settings must be an object")
    current = get_library(cfg)
    clean = _clean(patch, current)
    stored = {**_stored(cfg), **clean}
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (KEY, json.dumps(stored)))
    if "books_dirs" in clean:
        gone = [d for d in current["books_dirs"] if d not in clean["books_dirs"]]
        if gone:
            from .scanner import _scan_lock
            with _scan_lock:  # a scan already under way finishes first, and won't scan these again
                _forget_folders(cfg, gone)
    return get_library(cfg)


def _forget_folders(cfg: Config, roots: list[str]) -> None:
    """The admin took these folders out of the library: their books go (the files are untouched)."""
    from .scanner import _delete_book

    with session(cfg.db_path) as con:
        for root in roots:
            con.execute("DELETE FROM book_files WHERE root = ?", (root,))
        for r in con.execute("SELECT id FROM books b WHERE NOT EXISTS "
                             "(SELECT 1 FROM book_files f WHERE f.book_id = b.id)").fetchall():
            _delete_book(cfg, con, r["id"])

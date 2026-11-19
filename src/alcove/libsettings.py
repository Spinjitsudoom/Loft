"""Library settings, set by the admin in the app: the library's name, the books folders, where
uploads go, how often to scan, whether plain-text files count as books, and online lookups (with
optional Google Books and ISBNdb keys and a Hardcover token, which are kept here and never sent
back to the app).

Stored in the database (only what the admin changed). Until the admin saves a folder list, the one
from config.toml (or ALCOVE_BOOKS_DIRS) is used.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .config import Config
from .db import session

KEY = "library"
MAX_NAME = 40
MAX_FOLDERS = 10
SCAN_MINUTES = range(5, 1441)
API_KEY = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
SECRET = re.compile(r"^[!-~]{10,4000}$")  # a token or key: printable, no spaces

# The library's sections (its categories, for the stacks), suggested from the tags books have until
# the admin saves their own. Order matters: a book stands in the first section whose tags it has.
SUGGESTED_SECTIONS = [
    ("Manga", ["Manga", "Manhwa", "Manhua"]),
    ("Graphic novels", ["Comics & Graphic Novels", "Comics", "Graphic Novels", "Graphic Novel"]),
    ("Children’s", ["Juvenile Fiction", "Juvenile Nonfiction", "Children's", "Children’s", "Picture Books"]),
    ("Young adult", ["Young Adult Fiction", "Young Adult Nonfiction", "Young Adult"]),
    ("Historical", ["Historical Fiction", "Historical", "History"]),
    ("Fantasy", ["Fantasy", "Epic"]),
    ("Science fiction", ["Science Fiction", "Sci-Fi", "Dystopian"]),
    ("Horror", ["Horror"]),
    ("Thrillers & mystery", ["Thrillers", "Thriller", "Mystery", "Suspense", "Crime", "Mystery & Detective"]),
    ("Romance", ["Romance"]),
    ("Art & animation", ["Animation", "Performing Arts", "Art", "Design"]),
    ("Biography", ["Biography & Autobiography", "Biography", "Memoir"]),
    ("Science & nature", ["Science", "Nature", "Mathematics", "Technology & Engineering"]),
    ("Poetry", ["Poetry"]),
    ("Cooking", ["Cooking"]),
]
MAX_SECTIONS, MAX_SECTION_NAME, MAX_SECTION_TAGS = 30, 40, 50


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
        "auto_lookup": stored.get("auto_lookup", True),  # new books missing details are looked up after scans
        "join_requests": stored.get("join_requests", False),  # people may ask to join from the sign-in page
        "google_books": bool(google_books_key(cfg, stored)),  # whether a key is saved, never the key
        "hardcover": bool(hardcover_token(cfg, stored)),
        "isbndb": bool(isbndb_key(cfg, stored)[0]),
        "sections": stored["sections"] if isinstance(stored.get("sections"), list) else _suggested_sections(cfg),
        "sections_suggested": not isinstance(stored.get("sections"), list),
    }


def _suggested_sections(cfg: Config) -> list[dict]:
    """The suggested sections the library's books would fill (with only the tags they have)."""
    with session(cfg.db_path) as con:
        have = {r[0].casefold(): r[0] for r in con.execute(
            "SELECT DISTINCT j.value FROM books, json_each(books.tags) j WHERE j.type = 'text'")}
    out = []
    for name, tags in SUGGESTED_SECTIONS:
        found = [have[t.casefold()] for t in tags if t.casefold() in have]
        if found:
            out.append({"name": name, "tags": found})
    return out


def _sections(value) -> list[dict] | None:
    if value is None:
        return None  # back to the suggestions
    if not isinstance(value, list) or len(value) > MAX_SECTIONS:
        raise ValueError(f"sections must be a list of at most {MAX_SECTIONS}")
    out, names = [], set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("tags"), list):
            raise ValueError("sections: each needs a name and a list of tags")
        name = " ".join(item["name"].split())
        if not name or len(name) > MAX_SECTION_NAME:
            raise ValueError(f"sections: a name must be 1 to {MAX_SECTION_NAME} characters")
        if name.casefold() in names or name.casefold() == "other":
            raise ValueError(f"sections: there’s already a section called {name}")
        names.add(name.casefold())
        tags = list(dict.fromkeys(" ".join(t.split()) for t in item["tags"] if isinstance(t, str) and t.strip()))
        if len(tags) > MAX_SECTION_TAGS or any(len(t) > 60 for t in tags):
            raise ValueError(f"sections: at most {MAX_SECTION_TAGS} tags each, of up to 60 characters")
        out.append({"name": name, "tags": tags})
    return out


def google_books_key(cfg: Config, stored: dict | None = None) -> str:
    value = (_stored(cfg) if stored is None else stored).get("google_books_key")
    return value if isinstance(value, str) else ""


def hardcover_token(cfg: Config, stored: dict | None = None) -> str:
    value = (_stored(cfg) if stored is None else stored).get("hardcover_token")
    return value if isinstance(value, str) else ""


def isbndb_key(cfg: Config, stored: dict | None = None) -> tuple[str, str]:
    """The ISBNdb key and the address of the plan it works at (found when it was saved)."""
    stored = _stored(cfg) if stored is None else stored
    value, host = stored.get("isbndb_key"), stored.get("isbndb_host")
    if not isinstance(value, str) or not value or not isinstance(host, str) or not host:
        return "", ""
    return value, host


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
        elif key == "sections":
            value = _sections(value)
        elif key == "google_books_key":
            if not isinstance(value, str):
                raise ValueError("google_books_key must be text")
            value = value.strip()
            if value and not API_KEY.match(value):
                raise ValueError("google_books_key doesn’t look like a Google API key (they start with AIza)")
        elif key in ("hardcover_token", "isbndb_key"):
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            value = value.strip()
            if key == "hardcover_token" and value.lower().startswith("bearer "):
                value = value[7:].strip()  # Hardcover shows it with "Bearer " in front
            if value and not SECRET.match(value):
                raise ValueError(f"{'That token' if key == 'hardcover_token' else 'That key'} doesn’t look right; "
                                 "copy it again, whole")
        elif key in ("allow_txt", "online_lookups", "auto_lookup", "join_requests"):
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
    if clean.get("google_books_key") and clean.get("online_lookups", current["online_lookups"]):
        from .googlebooks import check_key
        check_key(clean["google_books_key"])
    if clean.get("hardcover_token") and clean.get("online_lookups", current["online_lookups"]):
        from . import hardcover
        hardcover.check_key(clean["hardcover_token"])
    if "isbndb_key" in clean:
        clean["isbndb_host"] = ""
        if clean["isbndb_key"]:
            from . import isbndb
            clean["isbndb_host"] = isbndb.check_key(clean["isbndb_key"])
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

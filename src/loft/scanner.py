"""Keeps the database in step with the books folders.

One book per Calibre entry (all its formats together) and one per loose file. Unchanged files
(same size and modification time) are skipped. A folder that can't be read, or that suddenly looks
empty (an SMB share that dropped shows as a bare mount point), is left alone: its books stay.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .calibre import CalibreBook, read_calibre
from .config import Config
from .covers import extract_cover, remove_cover, spine_colours, store_cover
from .db import session
from .filemeta import FileMeta, read_file_meta
from .formats import format_of
from . import libsettings
from .pages import prune_page_cache

log = logging.getLogger(__name__)

ARTICLES = ("the ", "a ", "an ")
LOGGED_EACH = 50   # books added (and removed) named one by one in the activity log per scan


@dataclass(frozen=True)
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0

    def json(self) -> dict:
        return {"added": self.added, "updated": self.updated, "removed": self.removed}


@dataclass
class _Found:
    fmt: str
    size: int
    mtime: float


def sort_title(title: str) -> str:
    low = title.lower()
    for a in ARTICLES:
        if low.startswith(a) and len(title) > len(a):
            return title[len(a):].strip()
    return title


def _walk(root: Path, allow_txt: bool = False) -> tuple[dict[Path, _Found], set[Path]]:
    """Every book file under root, and the folders and files that couldn't be read (their books
    must not be treated as gone). Raises OSError if root itself can't be listed."""
    found: dict[Path, _Found] = {}
    unreadable: set[Path] = set()
    stack = [root]
    first = True
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            if first:
                raise
            log.warning("Couldn't read folder %s; leaving its books as they are", folder)
            unreadable.add(folder)
            continue
        first = False
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=True):
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=True):
                    fmt = format_of(Path(e.name), allow_txt=allow_txt)
                    if fmt:
                        st = e.stat()
                        found[Path(e.path)] = _Found(fmt, st.st_size, st.st_mtime)
            except OSError:
                unreadable.add(Path(e.path))
    return found, unreadable


def _protected(path: Path, unreadable: set[Path]) -> bool:
    return path in unreadable or any(parent in unreadable for parent in path.parents)


# Columns each editable field covers: when the admin has set a field, scans leave all of them alone.
LOCK_COLUMNS = {"title": ("title", "sort_title", "title_from_name"), "authors": ("authors", "author_sort"),
                "series": ("series",), "series_index": ("series_index",), "description": ("description",),
                "publisher": ("publisher",), "published": ("published",), "language": ("language",),
                "tags": ("tags",)}


def locked_fields(con: sqlite3.Connection, book_id: int) -> set[str]:
    row = con.execute("SELECT locked FROM books WHERE id = ?", (book_id,)).fetchone()
    try:
        return set(json.loads(row["locked"])) if row else set()
    except (TypeError, ValueError):
        return set()


def index_book(con: sqlite3.Connection, book_id: int) -> None:
    """Bring the search index up to date with the book's row."""
    row = con.execute("SELECT title, authors, series, tags FROM books WHERE id = ?", (book_id,)).fetchone()
    con.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
    if row:
        con.execute("INSERT INTO books_fts(rowid, title, authors, series, tags) VALUES (?, ?, ?, ?, ?)",
                    (book_id, row["title"], " ".join(json.loads(row["authors"] or "[]")), row["series"],
                     " ".join(json.loads(row["tags"] or "[]"))))


def _write_book(con: sqlite3.Connection, book_id: int | None, *, title: str, authors: list[str], author_sort: str,
                series: str, series_index: float | None, description: str, publisher: str, published: str,
                language: str, tags: list[str], calibre_id: int | None, added_at: float,
                locked: list[str] | None = None, title_from_name: bool = False) -> int:
    now = time.time()
    values = dict(title=title, sort_title=sort_title(title), authors=json.dumps(authors),
                  author_sort=author_sort or (authors[0] if authors else ""), series=series,
                  series_index=series_index, description=description, publisher=publisher, published=published,
                  language=language, tags=json.dumps(tags), calibre_id=calibre_id, updated_at=now,
                  title_from_name=int(title_from_name))
    if book_id is None:
        values["added_at"] = added_at
        values["locked"] = json.dumps(sorted(locked or []))
        cols = ", ".join(values)
        book_id = con.execute(f"INSERT INTO books({cols}) VALUES ({', '.join('?' * len(values))})",
                              tuple(values.values())).lastrowid
    else:
        for name in locked_fields(con, book_id):
            for column in LOCK_COLUMNS.get(name, ()):
                values.pop(column, None)
        sets = ", ".join(f"{k} = ?" for k in values)
        con.execute(f"UPDATE books SET {sets} WHERE id = ?", (*values.values(), book_id))
    index_book(con, book_id)
    return book_id


def _set_cover(cfg: Config, con: sqlite3.Connection, book_id: int, image: bytes | None) -> None:
    if "cover" in locked_fields(con, book_id):
        return  # the admin chose this book's cover
    colour = spine = None
    if image:
        try:
            colour = store_cover(cfg, book_id, image)
            spine = spine_colours(cfg, book_id)
        except Exception as e:
            log.info("Couldn't use the cover for book %s: %s", book_id, e)
    if colour is None:
        remove_cover(cfg, book_id)
    con.execute("UPDATE books SET has_cover = ?, cover_color = ?, spine_colors = ? WHERE id = ?",
                (int(colour is not None), colour, spine, book_id))


def _upsert_file(con: sqlite3.Connection, book_id: int, path: Path, f: _Found, root: Path) -> None:
    con.execute("INSERT INTO book_files(book_id, path, format, size, mtime, root) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET book_id = excluded.book_id, format = excluded.format, "
                "size = excluded.size, mtime = excluded.mtime, root = excluded.root",
                (book_id, str(path), f.fmt, f.size, f.mtime, str(root)))


def _calibre_book(cfg: Config, con: sqlite3.Connection, cb: CalibreBook, path: Path, f: _Found, root: Path,
                  done: set[int], known_book_id: int | None) -> str:
    """Record a file Calibre knows about. Returns "added" or "updated"."""
    row = con.execute("SELECT b.id FROM books b WHERE b.calibre_id = ? AND EXISTS "
                      "(SELECT 1 FROM book_files f WHERE f.book_id = b.id AND f.root = ?)",
                      (cb.calibre_id, str(root))).fetchone()
    # A file that was first found loose (Calibre hadn't recorded it yet) keeps its book.
    book_id = row["id"] if row else known_book_id
    outcome = "updated" if book_id else "added"
    if cb.calibre_id not in done:
        done.add(cb.calibre_id)
        image = None
        if cb.cover:
            try:
                image = cb.cover.read_bytes()
            except OSError:
                image = None
        image = image or extract_cover(path, f.fmt)
        book_id = _write_book(con, book_id, title=cb.title, authors=cb.authors, author_sort=cb.author_sort,
                              series=cb.series, series_index=cb.series_index, description=cb.description,
                              publisher=cb.publisher, published=cb.published, language=cb.language, tags=cb.tags,
                              calibre_id=cb.calibre_id, added_at=cb.added or time.time())
        _set_cover(cfg, con, book_id, image)
    _upsert_file(con, book_id, path, f, root)
    return outcome


def _loose_book(cfg: Config, con: sqlite3.Connection, book_id: int | None, path: Path, f: _Found, root: Path) -> str:
    # Read the file before writing anything, so the database is only held for the writes themselves.
    meta: FileMeta = read_file_meta(path, f.fmt)
    image = extract_cover(path, f.fmt)
    outcome = "updated" if book_id else "added"
    book_id = _write_book(con, book_id, title=meta.title, authors=meta.authors, author_sort="", series=meta.series,
                          series_index=meta.series_index, description=meta.description, publisher=meta.publisher,
                          published=meta.published, language=meta.language, tags=[], calibre_id=None,
                          added_at=time.time(), title_from_name=meta.title_from_name)
    _set_cover(cfg, con, book_id, image)
    _upsert_file(con, book_id, path, f, root)
    return outcome


def _delete_book(cfg: Config, con: sqlite3.Connection, book_id: int) -> None:
    con.execute("DELETE FROM books WHERE id = ?", (book_id,))
    con.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
    remove_cover(cfg, book_id)


@dataclass
class _RootReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unreachable: bool = False
    unreadable: list[str] = field(default_factory=list)
    calibre_missing: list[str] = field(default_factory=list)
    added_books: list[tuple[int, str]] = field(default_factory=list)     # (id, title), for the activity log
    removed_books: list[tuple[int, str]] = field(default_factory=list)


def _scan_root(cfg: Config, con: sqlite3.Connection, root: Path, allow_txt: bool = False) -> _RootReport:
    known = {Path(r["path"]): r for r in con.execute(
        "SELECT id, book_id, path, size, mtime FROM book_files WHERE root = ?", (str(root),))}
    if not root.is_dir():
        log.warning("Books folder %s isn't reachable; leaving its books as they are", root)
        return _RootReport(unreachable=True)
    try:
        found, unreadable = _walk(root, allow_txt)
    except OSError as e:
        log.warning("Couldn't read books folder %s (%s); leaving its books as they are", root, e)
        return _RootReport(unreachable=True)
    if not found and known:
        log.warning("Books folder %s looks empty; leaving its books as they are (is the share mounted?)", root)
        return _RootReport(unreachable=True)

    db_file = root / "metadata.db"
    cal_mtime = str(db_file.stat().st_mtime) if db_file.is_file() else ""
    meta_key = f"calibre_mtime:{root}"
    row = con.execute("SELECT value FROM meta WHERE key = ?", (meta_key,)).fetchone()
    calibre_changed = (row["value"] if row else "") != cal_mtime
    calibre = read_calibre(root) if cal_mtime else {}
    calibre_ok = calibre is not None
    if not calibre_ok:  # e.g. Calibre was writing to it; try again next scan
        log.warning("Couldn't read Calibre's library in %s; new books there wait for the next scan", root)
        calibre = {}
    calibre_missing = sorted(str(p) for p in calibre if p not in found and not _protected(p, unreadable))

    added = updated = 0
    added_books: list[tuple[int, str]] = []
    done: set[int] = set()  # Calibre books already written this scan (several formats, one book)
    con.commit()
    for path, f in sorted(found.items()):
        k = known.get(path)
        unchanged = k is not None and k["size"] == f.size and k["mtime"] == f.mtime
        cb = calibre.get(path)
        if unchanged and not (cb and calibre_changed):
            continue
        if not calibre_ok:
            continue  # without Calibre's details a Calibre book would be imported wrongly
        try:
            if cb:
                outcome = _calibre_book(cfg, con, cb, path, f, root, done, k["book_id"] if k else None)
            else:
                outcome = _loose_book(cfg, con, k["book_id"] if k else None, path, f, root)
            con.commit()  # one book at a time: others can write in between, and progress survives a crash
        except Exception:
            con.rollback()
            log.exception("Couldn't add %s", path)
            continue
        if outcome == "added":
            added += 1
            if len(added_books) < LOGGED_EACH:
                new = con.execute("SELECT b.id, b.title FROM book_files f JOIN books b ON b.id = f.book_id "
                                  "WHERE f.path = ?", (str(path),)).fetchone()
                if new:
                    added_books.append((new["id"], new["title"]))
        else:
            updated += 1
    if calibre_ok:
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (meta_key, cal_mtime))

    removed = 0
    removed_books: list[tuple[int, str]] = []
    gone = [k for p, k in known.items() if p not in found and not _protected(p, unreadable)]
    for k in gone:
        con.execute("DELETE FROM book_files WHERE id = ?", (k["id"],))
    # Any book left without a file (gone, or whose file moved to another book) goes too.
    for r in con.execute("SELECT id, title FROM books b WHERE NOT EXISTS "
                         "(SELECT 1 FROM book_files f WHERE f.book_id = b.id)").fetchall():
        _delete_book(cfg, con, r["id"])
        removed += 1
        if len(removed_books) < LOGGED_EACH:
            removed_books.append((r["id"], r["title"]))
    return _RootReport(added, updated, removed, unreadable=sorted(str(p) for p in unreadable),
                       calibre_missing=calibre_missing, added_books=added_books, removed_books=removed_books)


_scan_lock = threading.Lock()  # one scan at a time; library changes that touch book files wait for it


def _nested(root: Path, roots: list[Path]) -> bool:
    """Whether root is inside another listed folder, or is an earlier-listed folder again by another path."""
    try:
        real = root.resolve()
        others = [(i, Path(r).resolve()) for i, r in enumerate(roots)]
    except OSError:
        return False
    mine = next(i for i, r in enumerate(roots) if Path(r) == root)
    return any(i != mine and (real.is_relative_to(other) and real != other or real == other and i < mine)
               for i, other in others)
REPORT_KEY = "last_scan"


def scan(cfg: Config) -> ScanResult:
    report = {"at": 0.0, "added": 0, "updated": 0, "removed": 0, "unreachable": [], "unreadable": [],
              "calibre_missing": []}
    added_books: list[tuple[int, str]] = []
    removed_books: list[tuple[int, str]] = []
    with _scan_lock:
        txt = libsettings.allow_txt(cfg)
        roots = libsettings.books_dirs(cfg)
        for root in roots:
            if str(root) not in libsettings.get_library(cfg)["books_dirs"]:
                continue  # taken out of the library while this scan was running
            if _nested(Path(root), roots):
                log.warning("Books folder %s is inside another books folder; scanning it once, as part of that one", root)
                continue
            with session(cfg.db_path) as con:
                r = _scan_root(cfg, con, Path(root), txt)
            for key in ("added", "updated", "removed"):
                report[key] += getattr(r, key)
            if r.unreachable:
                report["unreachable"].append(str(root))
            report["unreadable"] += r.unreadable
            report["calibre_missing"] += r.calibre_missing
            added_books += r.added_books
            removed_books += r.removed_books
        report["at"] = time.time()
        with session(cfg.db_path) as con:
            con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (REPORT_KEY, json.dumps(report)))
            _log_scan(con, report, added_books, removed_books)
    result = ScanResult(report["added"], report["updated"], report["removed"])
    log.info("Scan finished: %s added, %s updated, %s removed", result.added, result.updated, result.removed)
    return result


def _log_scan(con: sqlite3.Connection, report: dict, added: list[tuple[int, str]],
              removed: list[tuple[int, str]]) -> None:
    """The activity log: each book added or removed, up to LOGGED_EACH of each (a first scan can add
    thousands), then how many more; and the scan itself, when it changed anything."""
    from .activity import record

    for books, count, kind, text, more in ((added, report["added"], "books.added", "added (scan)", "added"),
                                           (removed, report["removed"], "books.removed",
                                            "removed (gone from the folder)", "removed")):
        for book_id, title in books[:LOGGED_EACH]:
            record(con, kind, text, book_id=book_id, book_title=title)
        rest = count - min(len(books), LOGGED_EACH)
        if rest > 0:
            record(con, kind, f"{more} {rest} more {'book' if rest == 1 else 'books'}")
    if report["added"] or report["updated"] or report["removed"]:
        record(con, "loft.scan", "scanned the library",
               details={k: report[k] for k in ("added", "updated", "removed")})


def last_report(cfg: Config) -> dict | None:
    """What the last scan found: counts, and the folders and files it couldn't get to."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (REPORT_KEY,)).fetchone()
    return json.loads(row["value"]) if row else None


class Scanner:
    """Scans at start, then every scan_interval_minutes, and whenever trigger() is called."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.running = False
        self.last: ScanResult | None = None
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        from .autofill import AutoFiller
        self.filler = AutoFiller(cfg)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="loft-scanner", daemon=True)
            self._thread.start()

    def trigger(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while True:
            self.running = True
            try:
                self.last = scan(self.cfg)
                from .check import check_files
                check_files(self.cfg)
                self.filler.trigger()
                prune_page_cache(self.cfg)
                from .uploads import prune_drafts
                prune_drafts(self.cfg)
            except Exception:
                log.exception("Scan failed")
            finally:
                self.running = False
            try:
                minutes = libsettings.get_library(self.cfg)["scan_interval_minutes"]
            except Exception:
                minutes = self.cfg.scan_interval_minutes
            self._wake.wait(timeout=max(1, minutes) * 60)
            self._wake.clear()

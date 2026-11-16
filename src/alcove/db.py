"""SQLite storage, in the data dir. WAL lets the scanner write while requests read."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    admin         INTEGER NOT NULL DEFAULT 0,
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    sort_title   TEXT NOT NULL,
    authors      TEXT NOT NULL DEFAULT '[]',   -- JSON list
    author_sort  TEXT NOT NULL DEFAULT '',
    series       TEXT NOT NULL DEFAULT '',
    series_index REAL,
    description  TEXT NOT NULL DEFAULT '',     -- plain text
    publisher    TEXT NOT NULL DEFAULT '',
    published    TEXT NOT NULL DEFAULT '',
    language     TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]',   -- JSON list
    calibre_id   INTEGER,
    cover_color  TEXT,
    has_cover    INTEGER NOT NULL DEFAULT 0,
    added_at     REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS books_added ON books(added_at);
CREATE INDEX IF NOT EXISTS books_series ON books(series);
CREATE INDEX IF NOT EXISTS books_calibre ON books(calibre_id);

CREATE TABLE IF NOT EXISTS book_files (
    id      INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    path    TEXT NOT NULL UNIQUE,
    format  TEXT NOT NULL,
    size    INTEGER NOT NULL,
    mtime   REAL NOT NULL,
    root    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS book_files_book ON book_files(book_id);

CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
    title, authors, series, tags, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS page_info (
    file_id INTEGER PRIMARY KEY REFERENCES book_files(id) ON DELETE CASCADE,
    mtime   REAL NOT NULL,
    count   INTEGER NOT NULL,
    sizes   TEXT NOT NULL,  -- JSON [[w, h], ...]
    toc     TEXT NOT NULL   -- JSON [{"title", "page", "level"}, ...]
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection that commits when the block ends cleanly and rolls back if it raises."""
    con = connect(path)
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

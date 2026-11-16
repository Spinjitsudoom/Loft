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

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data    TEXT NOT NULL  -- JSON, only what the person changed
);

CREATE TABLE IF NOT EXISTS progress (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    file_id    INTEGER NOT NULL,
    page       INTEGER NOT NULL,
    pages      INTEGER NOT NULL,
    position   REAL NOT NULL,
    finished   INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    locator    TEXT,  -- JSON {"chapter", "progress"} for flowing books
    PRIMARY KEY (user_id, book_id)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    file_id    INTEGER NOT NULL,
    page       INTEGER NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    locator    TEXT
);
CREATE INDEX IF NOT EXISTS bookmarks_user_book ON bookmarks(user_id, book_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# Columns added after a table first shipped: (table, column, type). Added to older databases on open.
MIGRATIONS = [
    ("progress", "locator", "TEXT"),
    ("bookmarks", "locator", "TEXT"),
]


def migrate(con: sqlite3.Connection) -> None:
    for table, column, kind in MIGRATIONS:
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if have and column not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    con.commit()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    migrate(con)
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

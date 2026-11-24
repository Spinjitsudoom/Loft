"""SQLite storage, in the data dir. WAL lets the scanner write while requests read."""

from __future__ import annotations

import sqlite3
import time
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
    updated_at   REAL NOT NULL,
    locked       TEXT NOT NULL DEFAULT '[]',   -- JSON list of fields the admin set; scans leave them alone
    title_from_name INTEGER                    -- 1 when the title was made from the file's name (NULL: not known yet)
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
    root    TEXT NOT NULL,
    layout  TEXT,                              -- JSON {"split", "wraparound"}: true, false or null (automatic)
    layout_rev INTEGER NOT NULL DEFAULT 0      -- bumped when the layout changes, so page images change too
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

CREATE TABLE IF NOT EXISTS shelves (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL COLLATE NOCASE,
    kind       TEXT NOT NULL DEFAULT 'own',  -- 'want' (Want to read) or 'own'
    created_at REAL NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS shelf_books (
    shelf_id INTEGER NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
    book_id  INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    added_at REAL NOT NULL,
    PRIMARY KEY (shelf_id, book_id)
);
CREATE INDEX IF NOT EXISTS shelf_books_book ON shelf_books(book_id);

-- A reading status set by hand (statuses.py); the rest are worked out from progress and Want to read.
CREATE TABLE IF NOT EXISTS book_status (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    status  TEXT NOT NULL,  -- unread, reading, incomplete, abandoned, finished
    set_at  REAL NOT NULL,
    PRIMARY KEY (user_id, book_id)
);

CREATE TABLE IF NOT EXISTS check_ignored (
    kind TEXT NOT NULL,
    key  TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS file_checks (
    file_id INTEGER PRIMARY KEY REFERENCES book_files(id) ON DELETE CASCADE,
    mtime   REAL NOT NULL,
    status  TEXT NOT NULL  -- 'ok', 'damaged' or 'protected'
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Members (M5): notifications, asking to join, submissions, requests and discussion.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    link       TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    read_at    REAL
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, created_at);

CREATE TABLE IF NOT EXISTS join_requests (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    token      TEXT NOT NULL UNIQUE,
    filename   TEXT NOT NULL,
    format     TEXT NOT NULL,
    details    TEXT NOT NULL,
    right_to_left INTEGER NOT NULL DEFAULT 0,
    cover_url  TEXT,
    status     TEXT NOT NULL DEFAULT 'waiting',
    reason     TEXT NOT NULL DEFAULT '',
    book_id    INTEGER REFERENCES books(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    decided_at REAL
);

CREATE TABLE IF NOT EXISTS requests (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    author     TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    reason     TEXT NOT NULL DEFAULT '',
    book_id    INTEGER REFERENCES books(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    decided_at REAL
);
CREATE TABLE IF NOT EXISTS request_votes (
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (request_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    parent_id  INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    position   REAL NOT NULL DEFAULT 0,
    place      TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    edited_at  REAL,
    removed    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_book ON messages(book_id, id);

-- New books filled in by themselves (autofill.py): where each is, and what was filled, to undo it.
CREATE TABLE IF NOT EXISTS autofill (
    book_id  INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    state    TEXT NOT NULL,  -- waiting, filled, unsure, complete, before (there first), undone
    tries    INTEGER NOT NULL DEFAULT 0,
    at       REAL,
    sources  TEXT NOT NULL DEFAULT '[]',
    filled   TEXT NOT NULL DEFAULT '[]',
    previous TEXT NOT NULL DEFAULT '{}',
    after    TEXT NOT NULL DEFAULT '{}'
);

-- 0.2.0: the activity log (no foreign keys: an entry outlives the person and book it names).
CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY,
    at         REAL NOT NULL,
    user_id    INTEGER,
    user_name  TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    book_id    INTEGER,
    book_title TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL,
    details    TEXT
);
CREATE INDEX IF NOT EXISTS activity_at ON activity(at);
CREATE INDEX IF NOT EXISTS activity_user ON activity(user_id, id);

-- 0.2.0: ratings (ratings.py), one per person per book.
CREATE TABLE IF NOT EXISTS ratings (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id  INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    stars    INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    rated_at REAL NOT NULL,
    PRIMARY KEY (user_id, book_id)
);
CREATE INDEX IF NOT EXISTS ratings_book ON ratings(book_id);
"""


# Columns added after a table first shipped: (table, column, type). Added to older databases on open.
MIGRATIONS = [
    ("progress", "locator", "TEXT"),
    ("bookmarks", "locator", "TEXT"),
    ("books", "locked", "TEXT NOT NULL DEFAULT '[]'"),
    ("books", "title_from_name", "INTEGER"),
    ("book_files", "layout", "TEXT"),
    ("book_files", "layout_rev", "INTEGER NOT NULL DEFAULT 0"),
]


def migrate(con: sqlite3.Connection) -> None:
    for table, column, kind in MIGRATIONS:
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if have and column not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    con.commit()


def _use_wal(con: sqlite3.Connection) -> None:
    """WAL lets readers carry on while a scan writes. Switching a new database to it needs a lock
    SQLite won't wait for, and when Loft first starts several parts open it at once: so only switch
    when it isn't already, and try again for a few seconds if another part is switching it now."""
    for attempt in range(100):
        try:
            if con.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                con.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == 99:
                raise
            time.sleep(0.05)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    _use_wal(con)
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

"""Each person's shelves: "Want to read" (always there) and shelves of their own.

"Finished" isn't a shelf you fill: it's the books you've read to the end (see library.list_books).
Nobody can see or change another person's shelves; asking for one is the same as asking for one
that doesn't exist.
"""

from __future__ import annotations

import time

from .config import Config
from .db import session

WANT = "Want to read"
MAX_NAME = 40


def _clean(name) -> str:
    if not isinstance(name, str):
        raise ValueError("A shelf needs a name")
    name = " ".join(name.split())
    if not name:
        raise ValueError("A shelf needs a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"Shelf names can be at most {MAX_NAME} characters")
    return name


def _ensure_want(con, user_id: int) -> None:
    if not con.execute("SELECT 1 FROM shelves WHERE user_id = ? AND kind = 'want'", (user_id,)).fetchone():
        con.execute("INSERT INTO shelves(user_id, name, kind, created_at) VALUES (?, ?, 'want', ?)",
                    (user_id, WANT, time.time()))


def _shelf(con, user_id: int, shelf_id) -> dict:
    row = con.execute("SELECT * FROM shelves WHERE id = ? AND user_id = ?", (shelf_id, user_id)).fetchone()
    if row is None:
        raise LookupError(shelf_id)
    return dict(row)


def _json(con, row) -> dict:
    count = con.execute("SELECT COUNT(*) FROM shelf_books WHERE shelf_id = ?", (row["id"],)).fetchone()[0]
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "count": count}


def list_shelves(cfg: Config, user_id: int) -> list[dict]:
    with session(cfg.db_path) as con:
        _ensure_want(con, user_id)
        rows = con.execute("SELECT * FROM shelves WHERE user_id = ? ORDER BY kind = 'own', name COLLATE NOCASE",
                           (user_id,)).fetchall()
        return [_json(con, r) for r in rows]


def _unique(con, user_id: int, name: str, shelf_id: int | None = None) -> None:
    clash = con.execute("SELECT id FROM shelves WHERE user_id = ? AND name = ? COLLATE NOCASE AND id IS NOT ?",
                        (user_id, name, shelf_id)).fetchone()
    if clash or (name.casefold() == WANT.casefold() and shelf_id is None):
        raise ValueError(f"You already have a shelf called {name}")


def create(cfg: Config, user_id: int, name) -> dict:
    name = _clean(name)
    with session(cfg.db_path) as con:
        _ensure_want(con, user_id)
        _unique(con, user_id, name)
        sid = con.execute("INSERT INTO shelves(user_id, name, kind, created_at) VALUES (?, ?, 'own', ?)",
                          (user_id, name, time.time())).lastrowid
        return _json(con, _shelf(con, user_id, sid))


def rename(cfg: Config, user_id: int, shelf_id: int, name) -> dict:
    name = _clean(name)
    with session(cfg.db_path) as con:
        shelf = _shelf(con, user_id, shelf_id)
        if shelf["kind"] == "want":
            raise ValueError("Want to read keeps its name")
        _unique(con, user_id, name, shelf_id)
        if name.casefold() == WANT.casefold():
            raise ValueError(f"You already have a shelf called {name}")
        con.execute("UPDATE shelves SET name = ? WHERE id = ?", (name, shelf_id))
        return _json(con, _shelf(con, user_id, shelf_id))


def delete(cfg: Config, user_id: int, shelf_id: int) -> None:
    with session(cfg.db_path) as con:
        if _shelf(con, user_id, shelf_id)["kind"] == "want":
            raise ValueError("Want to read can’t be removed")
        con.execute("DELETE FROM shelves WHERE id = ?", (shelf_id,))


def add(cfg: Config, user_id: int, shelf_id: int, book_id: int) -> None:
    from . import loans

    with session(cfg.db_path) as con:
        shelf = _shelf(con, user_id, shelf_id)
        if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
            raise LookupError(book_id)
        now = time.time()
        added = con.execute("INSERT OR IGNORE INTO shelf_books(shelf_id, book_id, added_at) VALUES (?, ?, ?)",
                            (shelf_id, book_id, now)).rowcount
        if added and shelf["kind"] == "want":   # Want to read is a status too: a book you want isn't out
            loans.marked(con, user_id, book_id, "want", now)


def remove(cfg: Config, user_id: int, shelf_id: int, book_id: int) -> None:
    with session(cfg.db_path) as con:
        _shelf(con, user_id, shelf_id)
        con.execute("DELETE FROM shelf_books WHERE shelf_id = ? AND book_id = ?", (shelf_id, book_id))


def for_book(cfg: Config, user_id: int, book_id: int) -> list[int]:
    with session(cfg.db_path) as con:
        return [r[0] for r in con.execute(
            "SELECT s.id FROM shelf_books sb JOIN shelves s ON s.id = sb.shelf_id "
            "WHERE s.user_id = ? AND sb.book_id = ? ORDER BY s.kind = 'own', s.name COLLATE NOCASE", (user_id, book_id))]

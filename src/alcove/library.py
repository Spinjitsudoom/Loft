"""What the library screens show: the home rows, browsing, a book's page and search."""

from __future__ import annotations

import json
import re

from .config import Config
from .db import session

RECENT = 15
SERIES_ROWS = 8
TAG_ROWS = 6
TAG_ROW_BOOKS = 20
TAG_MIN_BOOKS = 3
SORTS = {
    "title": "sort_title COLLATE NOCASE, id",
    "added": "added_at DESC, id DESC",
    "author": "author_sort COLLATE NOCASE, sort_title COLLATE NOCASE, id",
}
SERIES_ORDER = "COALESCE(series_index, 1e9), sort_title COLLATE NOCASE"


def book_card(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "authors": json.loads(row["authors"] or "[]"),
        "series": row["series"],
        "series_index": row["series_index"],
        "has_cover": bool(row["has_cover"]),
        "color": row["cover_color"],
    }


def home(cfg: Config, user) -> dict:
    with session(cfg.db_path) as con:
        recent = [book_card(r) for r in con.execute(
            f"SELECT * FROM books ORDER BY {SORTS['added']} LIMIT ?", (RECENT,))]
        if not recent:
            return {"hero": None, "rows": []}
        rows = [{"title": "Recently added", "kind": "recent", "value": None, "books": recent}]

        for s in con.execute(
                "SELECT series FROM books WHERE series != '' GROUP BY series HAVING COUNT(*) >= 2 "
                "ORDER BY MAX(added_at) DESC LIMIT ?", (SERIES_ROWS,)):
            books = [book_card(r) for r in con.execute(
                f"SELECT * FROM books WHERE series = ? ORDER BY {SERIES_ORDER}", (s["series"],))]
            rows.append({"title": s["series"], "kind": "series", "value": s["series"], "books": books})

        for t in con.execute(
                "SELECT j.value AS tag, COUNT(*) AS n FROM books, json_each(books.tags) j "
                "GROUP BY j.value HAVING n >= ? ORDER BY n DESC, j.value LIMIT ?", (TAG_MIN_BOOKS, TAG_ROWS)):
            books = [book_card(r) for r in con.execute(
                "SELECT books.* FROM books, json_each(books.tags) j WHERE j.value = ? "
                f"ORDER BY {SORTS['title']} LIMIT ?", (t["tag"], TAG_ROW_BOOKS))]
            rows.append({"title": t["tag"], "kind": "tag", "value": t["tag"], "books": books})
    return {"hero": recent[0], "rows": rows}


def _filter(kind: str | None, value: str | None) -> tuple[str, tuple]:
    if not kind or value is None:
        return "", ()
    if kind == "series":
        return "WHERE series = ?", (value,)
    if kind == "tag":
        return "WHERE EXISTS (SELECT 1 FROM json_each(books.tags) j WHERE j.value = ?)", (value,)
    if kind == "author":
        return "WHERE EXISTS (SELECT 1 FROM json_each(books.authors) j WHERE j.value = ?)", (value,)
    raise ValueError(f"Unknown filter {kind!r}")


def list_books(cfg: Config, *, kind: str | None, value: str | None, sort: str = "title",
               offset: int = 0, limit: int = 60) -> dict:
    where, args = _filter(kind, value)
    order = SERIES_ORDER if kind == "series" and sort == "title" else SORTS.get(sort, SORTS["title"])
    with session(cfg.db_path) as con:
        total = con.execute(f"SELECT COUNT(*) FROM books {where}", args).fetchone()[0]
        books = [book_card(r) for r in con.execute(
            f"SELECT * FROM books {where} ORDER BY {order} LIMIT ? OFFSET ?", (*args, limit, offset))]
    return {"total": total, "books": books}


def get_book(cfg: Config, book_id: int) -> dict | None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row is None:
            return None
        files = [{"id": f["id"], "format": f["format"], "size": f["size"]} for f in con.execute(
            "SELECT id, format, size FROM book_files WHERE book_id = ? ORDER BY format", (book_id,))]
        series_books = []
        if row["series"]:
            series_books = [book_card(r) for r in con.execute(
                f"SELECT * FROM books WHERE series = ? AND id != ? ORDER BY {SERIES_ORDER}", (row["series"], book_id))]
    return {
        **book_card(row),
        "description": row["description"],
        "publisher": row["publisher"],
        "published": row["published"],
        "language": row["language"],
        "tags": json.loads(row["tags"] or "[]"),
        "files": files,
        "series_books": series_books,
    }


FTS_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


def search(cfg: Config, q: str, limit: int = 40) -> list[dict]:
    words = [w for w in re.findall(r"\w+", q or "") if w.upper() not in FTS_KEYWORDS]
    if not words:
        return []
    match = " ".join(f'"{w}"*' for w in words)
    with session(cfg.db_path) as con:
        return [book_card(r) for r in con.execute(
            "SELECT books.* FROM books_fts JOIN books ON books.id = books_fts.rowid "
            "WHERE books_fts MATCH ? ORDER BY bm25(books_fts), books.sort_title LIMIT ?", (match, limit))]

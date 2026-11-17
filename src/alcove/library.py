"""What the library screens show: the home rows, browsing, a book's page and search."""

from __future__ import annotations

import json
import re

from .config import Config
from .db import session
from .flow import READABLE_FLOW
from .pages import READABLE as PAGE_FORMATS
from .reading import get_progress, in_progress
from .settings import DEFAULTS, get_settings

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
        "cover_v": int(row["updated_at"]),  # changes when the cover might have, so browsers fetch it again
    }


def home(cfg: Config, user) -> dict:
    """The home screen for this person: a hero book, then rows in the order they chose."""
    look = get_settings(cfg, user.id)["look"] if user else DEFAULTS["look"]
    reading_now = in_progress(cfg, user.id) if user else []
    rows_by_kind: dict[str, list[dict]] = {"continue": [], "recent": [], "series": [], "genres": []}
    with session(cfg.db_path) as con:
        recent = [book_card(r) for r in con.execute(
            f"SELECT * FROM books ORDER BY {SORTS['added']} LIMIT ?", (RECENT,))]
        if not recent:
            return {"hero": None, "hero_kind": None, "hero_progress": None, "rows": []}
        rows_by_kind["recent"].append({"title": "Recently added", "kind": "recent", "value": None, "books": recent})

        for s in con.execute(
                "SELECT series FROM books WHERE series != '' GROUP BY series HAVING COUNT(*) >= 2 "
                "ORDER BY MAX(added_at) DESC LIMIT ?", (SERIES_ROWS,)):
            books = [book_card(r) for r in con.execute(
                f"SELECT * FROM books WHERE series = ? ORDER BY {SERIES_ORDER}", (s["series"],))]
            rows_by_kind["series"].append({"title": s["series"], "kind": "series", "value": s["series"], "books": books})

        for t in con.execute(
                "SELECT j.value AS tag, COUNT(*) AS n FROM books, json_each(books.tags) j "
                "GROUP BY j.value HAVING n >= ? ORDER BY n DESC, j.value LIMIT ?", (TAG_MIN_BOOKS, TAG_ROWS)):
            books = [book_card(r) for r in con.execute(
                "SELECT books.* FROM books, json_each(books.tags) j WHERE j.value = ? "
                f"ORDER BY {SORTS['title']} LIMIT ?", (t["tag"], TAG_ROW_BOOKS))]
            rows_by_kind["genres"].append({"title": t["tag"], "kind": "tag", "value": t["tag"], "books": books})

    if len(reading_now) >= 2:
        rows_by_kind["continue"].append({"title": "Continue reading", "kind": "continue", "value": None,
                                         "books": [{**card, "progress": p} for card, p in reading_now]})
    rows = [row for r in look["home_rows"] if r["visible"] for row in rows_by_kind[r["kind"]]]
    if reading_now:
        card, progress = reading_now[0]
        return {"hero": card, "hero_kind": "continue", "hero_progress": progress, "rows": rows}
    return {"hero": recent[0], "hero_kind": "new", "hero_progress": None, "rows": rows}


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


def get_book(cfg: Config, book_id: int, user=None) -> dict | None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row is None:
            return None
        files = [{"id": f["id"], "format": f["format"], "size": f["size"], "readable": readable(f["format"])}
                 for f in con.execute(
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
        "progress": get_progress(cfg, user.id, book_id) if user else None,
    }


def readable(fmt: str) -> str | None:
    """How the reader shows a format: as page images, as flowing text, or not at all (download only)."""
    if fmt in PAGE_FORMATS:
        return "pages"
    return "flow" if fmt in READABLE_FLOW else None


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

"""What the library screens show: the home rows, browsing, a book's page and search."""

from __future__ import annotations

import json
import threading

from . import fuzzy
from .config import Config
from .db import session
from .flow import READABLE_FLOW
from .pages import READABLE as PAGE_FORMATS, file_layout, is_arranged
from .reading import get_progress, in_progress
from .settings import DEFAULTS, get_settings
from . import shelves as shelf_store
from . import loans, ratings, statuses

RECENT = 15
SERIES_ROWS = 8
TAG_ROWS = 6
TAG_ROW_BOOKS = 20
TAG_MIN_BOOKS = 3
SORTS = {
    "title": "sort_title COLLATE NOCASE, id",
    "added": "added_at DESC, id DESC",
    "author": "author_sort COLLATE NOCASE, sort_title COLLATE NOCASE, id",
    # Highest rated: by the average (books no one has rated last), then by how many rated.
    "rating": "(SELECT AVG(stars) FROM ratings r WHERE r.book_id = books.id) IS NULL, "
              "(SELECT AVG(stars) FROM ratings r WHERE r.book_id = books.id) DESC, "
              "(SELECT COUNT(*) FROM ratings r WHERE r.book_id = books.id) DESC, sort_title COLLATE NOCASE, id",
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
    rows_by_kind: dict[str, list[dict]] = {"continue": [], "shelves": [], "recent": [], "series": [], "genres": []}
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

    if user:
        rows_by_kind["shelves"] = _shelf_rows(cfg, user)
    if len(reading_now) >= 2:
        rows_by_kind["continue"].append({"title": "Continue reading", "kind": "continue", "value": None,
                                         "books": [{**card, "progress": p} for card, p in reading_now]})
    rows = [row for r in look["home_rows"] if r["visible"] for row in rows_by_kind[r["kind"]]]
    if reading_now:
        card, progress = reading_now[0]
        return {"hero": card, "hero_kind": "continue", "hero_progress": progress, "rows": rows}
    return {"hero": recent[0], "hero_kind": "new", "hero_progress": None, "rows": rows}


SHELF_ROW_BOOKS = 20


def _shelf_rows(cfg: Config, user) -> list[dict]:
    rows = []
    with session(cfg.db_path) as con:
        for shelf in shelf_store.list_shelves(cfg, user.id):
            if shelf["count"]:
                books = [book_card(r) for r in con.execute(
                    "SELECT b.* FROM shelf_books sb JOIN books b ON b.id = sb.book_id WHERE sb.shelf_id = ? "
                    "ORDER BY sb.added_at DESC LIMIT ?", (shelf["id"], SHELF_ROW_BOOKS))]
                rows.append({"title": shelf["name"], "kind": "shelf", "value": str(shelf["id"]), "books": books})
        mine = statuses.statuses_for(con, user.id)

        def having(status: str) -> list[dict]:
            ids = sorted((bid for bid, (s, _) in mine.items() if s == status), key=lambda bid: -mine[bid][1])
            return _cards(con, ids[:SHELF_ROW_BOOKS])

        incomplete, finished = having("incomplete"), having("finished")
    # Books stopped partway, to pick up again; then the ones read to the end.
    if incomplete:
        rows.append({"title": "Incomplete", "kind": "status", "value": "incomplete", "books": incomplete})
    if finished:
        rows.append({"title": "Finished", "kind": "finished", "value": "", "books": finished})
    return rows


def _cards(con, ids: list[int]) -> list[dict]:
    """Book cards for these ids, in this order."""
    if not ids:
        return []
    rows = {r["id"]: r for r in con.execute(f"SELECT * FROM books WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [book_card(rows[i]) for i in ids if i in rows]


def _filter(kind: str | None, value: str | None, user=None, cfg: Config | None = None) -> tuple[str, tuple]:
    if kind in ("shelf", "finished", "status"):
        if user is None:
            raise LookupError(kind)
        if kind in ("finished", "status"):
            # This person's books with a reading status ("finished" is the older way to ask for Finished).
            status = "finished" if kind == "finished" else value
            if status not in statuses.STATUSES:
                raise ValueError(f"Unknown reading status {status!r}")
            with session(cfg.db_path) as con:
                mine = statuses.statuses_for(con, user.id)
            if status == "unread":   # Not started: also every book with no status at all
                others = [bid for bid, (s, _) in mine.items() if s != "unread"]
                return "WHERE id NOT IN (SELECT value FROM json_each(?))", (json.dumps(others),)
            return ("WHERE id IN (SELECT value FROM json_each(?))",
                    (json.dumps([bid for bid, (s, _) in mine.items() if s == status]),))
        # Only the person's own shelf: someone else's matches nothing (and list_books says it doesn't exist).
        return ("WHERE id IN (SELECT sb.book_id FROM shelf_books sb JOIN shelves s ON s.id = sb.shelf_id "
                "WHERE s.id = ? AND s.user_id = ?)", (value, user.id))
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
               offset: int = 0, limit: int = 60, user=None) -> dict:
    where, args = _filter(kind, value, user, cfg)
    if kind == "shelf":
        with session(cfg.db_path) as con:
            if not con.execute("SELECT 1 FROM shelves WHERE id = ? AND user_id = ?", (value, user.id)).fetchone():
                raise LookupError(value)
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
        files = []
        for f in con.execute("SELECT id, format, size, layout FROM book_files WHERE book_id = ? ORDER BY format",
                             (book_id,)):
            entry = {"id": f["id"], "format": f["format"], "size": f["size"], "readable": readable(f["format"])}
            if entry["readable"] == "pages":
                entry["layout"] = file_layout(f)
                entry["arranged"] = is_arranged(f)  # the admin changed its page order or hid pages
            files.append(entry)
        series_books = []
        if row["series"]:
            series_books = [book_card(r) for r in con.execute(
                f"SELECT * FROM books WHERE series = ? AND id != ? ORDER BY {SERIES_ORDER}", (row["series"], book_id))]
        rating = ratings.summary(con, book_id, user.id if user else None)
        loan = loans.loan_for(con, user.id if user else None, book_id)
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
        "shelves": shelf_store.for_book(cfg, user.id, book_id) if user else [],
        "status": statuses.get_status(cfg, user.id, book_id)["status"] if user else "unread",
        "rating": rating,
        "loan": loan,
    }


def readable(fmt: str) -> str | None:
    """How the reader shows a format: as page images, as flowing text, or not at all (download only)."""
    if fmt in PAGE_FORMATS:
        return "pages"
    return "flow" if fmt in READABLE_FLOW else None


_indexes: dict[str, tuple[tuple, fuzzy.Index]] = {}   # per database: (what the books were like, the index)
_index_lock = threading.Lock()


def _search_index(cfg: Config, con) -> fuzzy.Index:
    """The word index of the library, built again only when its books have changed (added, removed, or
    any detail edited: every change stamps updated_at)."""
    signature = tuple(con.execute("SELECT count(*), max(updated_at), max(id) FROM books").fetchone())
    key = str(cfg.db_path)
    with _index_lock:
        kept = _indexes.get(key)
        if kept and kept[0] == signature:
            return kept[1]
        rows = con.execute("SELECT id, title, sort_title, series, authors, tags, description FROM books").fetchall()
        index = fuzzy.Index({"id": r["id"], "title": r["title"], "sort_title": r["sort_title"], "series": r["series"],
                             "authors": json.loads(r["authors"] or "[]"), "tags": json.loads(r["tags"] or "[]"),
                             "description": r["description"]} for r in rows)
        _indexes[key] = (signature, index)
        return index


def search(cfg: Config, q: str, limit: int = 40) -> list[dict]:
    """Books for the words typed, best match first (fuzzy.py): in any order, with typos, from the title,
    series, authors, tags or description."""
    if not fuzzy.words(q or ""):
        return []
    with session(cfg.db_path) as con:
        ids = _search_index(cfg, con).rank(q, limit)
        if not ids:
            return []
        rows = {r["id"]: r for r in con.execute(
            f"SELECT * FROM books WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [book_card(rows[i]) for i in ids if i in rows]


def merge_books(cfg: Config, into: int, other: int) -> None:
    """Make one book of two: other's files, shelf places, bookmarks, reading progress and statuses move
    to into (the newer progress or status wins when someone has both), and other goes. Every detail of into is locked,
    so a Calibre change can't pull them apart again. The files themselves are untouched."""
    import time

    from .editing import FIELDS
    from .scanner import _delete_book

    if into == other:
        raise ValueError("Pick two different books to merge")
    with session(cfg.db_path) as con:
        for book_id in (into, other):
            if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                raise LookupError(book_id)
        con.execute("UPDATE book_files SET book_id = ? WHERE book_id = ?", (into, other))
        con.execute("INSERT OR IGNORE INTO shelf_books(shelf_id, book_id, added_at) "
                    "SELECT shelf_id, ?, added_at FROM shelf_books WHERE book_id = ?", (into, other))
        con.execute("UPDATE bookmarks SET book_id = ? WHERE book_id = ?", (into, other))
        for p in con.execute("SELECT * FROM progress WHERE book_id = ?", (other,)).fetchall():
            mine = con.execute("SELECT updated_at FROM progress WHERE book_id = ? AND user_id = ?",
                               (into, p["user_id"])).fetchone()
            if mine is None or p["updated_at"] > mine["updated_at"]:
                con.execute("INSERT OR REPLACE INTO progress(user_id, book_id, file_id, page, pages, position, "
                            "finished, updated_at, locator) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (p["user_id"], into, p["file_id"], p["page"], p["pages"], p["position"], p["finished"],
                             p["updated_at"], p["locator"]))
        con.execute("INSERT INTO book_status(user_id, book_id, status, set_at) "
                    "SELECT user_id, ?, status, set_at FROM book_status WHERE book_id = ? AND true "
                    "ON CONFLICT(user_id, book_id) DO UPDATE SET status = excluded.status, set_at = excluded.set_at "
                    "WHERE excluded.set_at > book_status.set_at", (into, other))
        _delete_book(cfg, con, other)
        con.execute("UPDATE books SET locked = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(sorted([*FIELDS, "cover"])), time.time(), into))

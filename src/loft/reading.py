"""Where each person is in each book, and their bookmarks.

Progress carries the time the reader was on that page, so a save that arrives late (a phone coming
back online) never moves someone back past where they've read on another device.
"""

from __future__ import annotations

import json
import math
import time

from .config import Config
from . import statuses
from .db import session

CLOCK_SLACK = 60  # seconds a device's clock may run ahead of the server's
PROGRESS_FIELDS = ("file_id", "page", "pages", "position", "finished", "updated_at", "locator")


def check_locator(locator) -> dict | None:
    """Where you are in a flowing book: a chapter and how far through it (0–1)."""
    if locator is None:
        return None
    if (not isinstance(locator, dict) or set(locator) != {"chapter", "progress"}
            or not isinstance(locator["chapter"], int) or isinstance(locator["chapter"], bool) or locator["chapter"] < 0
            or not isinstance(locator["progress"], (int, float)) or isinstance(locator["progress"], bool)
            or not math.isfinite(locator["progress"])):
        raise ValueError("A place in a book is a chapter number and how far through it")
    return {"chapter": locator["chapter"], "progress": min(1.0, max(0.0, float(locator["progress"])))}


def _locator(text):
    return json.loads(text) if text else None


def _progress(row) -> dict:
    return {"file_id": row["file_id"], "page": row["page"], "pages": row["pages"], "position": row["position"],
            "finished": bool(row["finished"]), "updated_at": row["updated_at"], "locator": _locator(row["locator"])}


def get_progress(cfg: Config, user_id: int, book_id: int) -> dict | None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM progress WHERE user_id = ? AND book_id = ?", (user_id, book_id)).fetchone()
    return _progress(row) if row else None


def save_progress(cfg: Config, user_id: int, book_id: int, *, file_id: int, page: int, pages: int,
                  at: float | None = None, locator: dict | None = None) -> dict:
    locator = check_locator(locator)
    now = time.time()
    at = now if at is None else float(at)
    if not math.isfinite(at):
        raise ValueError("The reading time must be a real time")
    at = min(at, now + CLOCK_SLACK)  # a device whose clock runs ahead can't lock out the others
    pages = max(1, int(pages))
    page = min(max(0, int(page)), pages - 1)
    position = min(1.0, max(0.0, page / max(1, pages - 1)))
    finished = page >= pages - 1
    with session(cfg.db_path) as con:
        con.execute(
            "INSERT INTO progress(user_id, book_id, file_id, page, pages, position, finished, updated_at, locator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, book_id) DO UPDATE SET "
            "file_id = excluded.file_id, page = excluded.page, pages = excluded.pages, position = excluded.position, "
            "finished = excluded.finished, updated_at = excluded.updated_at, locator = excluded.locator "
            "WHERE excluded.updated_at >= progress.updated_at",
            (user_id, book_id, file_id, page, pages, position, int(finished), at,
             json.dumps(locator) if locator else None))
        statuses.read_now(con, user_id, book_id, at)
    return get_progress(cfg, user_id, book_id)


def in_progress(cfg: Config, user_id: int, limit: int = 20) -> list[tuple[dict, dict | None]]:
    """The books this person is reading (status Reading), the latest read or set first, with their
    progress: None for a book set to Reading by hand that has no place to continue from (never opened,
    or read to the end before)."""
    from .library import book_card

    with session(cfg.db_path) as con:
        mine = statuses.statuses_for(con, user_id)
        ids = sorted((bid for bid, (s, _) in mine.items() if s == "reading"), key=lambda bid: -mine[bid][1])[:limit]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        books = {r["id"]: r for r in con.execute(f"SELECT * FROM books WHERE id IN ({marks})", ids)}
        places = {r["book_id"]: r for r in con.execute(
            f"SELECT * FROM progress WHERE user_id = ? AND finished = 0 AND book_id IN ({marks})", (user_id, *ids))}
    return [(book_card(books[bid]), _progress(places[bid]) if bid in places else None) for bid in ids if bid in books]


def _bookmark(row) -> dict:
    return {"id": row["id"], "file_id": row["file_id"], "page": row["page"], "note": row["note"],
            "created_at": row["created_at"], "locator": _locator(row["locator"])}


def list_bookmarks(cfg: Config, user_id: int, book_id: int) -> list[dict]:
    with session(cfg.db_path) as con:
        return [_bookmark(r) for r in con.execute(
            "SELECT * FROM bookmarks WHERE user_id = ? AND book_id = ? ORDER BY page, id", (user_id, book_id))]


def add_bookmark(cfg: Config, user_id: int, book_id: int, *, file_id: int, page: int, note: str = "",
                 locator: dict | None = None) -> dict:
    locator = check_locator(locator)
    with session(cfg.db_path) as con:
        bid = con.execute("INSERT INTO bookmarks(user_id, book_id, file_id, page, note, created_at, locator) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (user_id, book_id, file_id, max(0, int(page)), (note or "")[:500], time.time(),
                           json.dumps(locator) if locator else None)).lastrowid
        return _bookmark(con.execute("SELECT * FROM bookmarks WHERE id = ?", (bid,)).fetchone())


def delete_bookmark(cfg: Config, user_id: int, bookmark_id: int) -> bool:
    with session(cfg.db_path) as con:
        return con.execute("DELETE FROM bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, user_id)).rowcount > 0

"""Where each person is in each book, and their bookmarks.

Progress carries the time the reader was on that page, so a save that arrives late (a phone coming
back online) never moves someone back past where they've read on another device.
"""

from __future__ import annotations

import time

from .config import Config
from .db import session

PROGRESS_FIELDS = ("file_id", "page", "pages", "position", "finished", "updated_at")


def _progress(row) -> dict:
    return {"file_id": row["file_id"], "page": row["page"], "pages": row["pages"], "position": row["position"],
            "finished": bool(row["finished"]), "updated_at": row["updated_at"]}


def get_progress(cfg: Config, user_id: int, book_id: int) -> dict | None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM progress WHERE user_id = ? AND book_id = ?", (user_id, book_id)).fetchone()
    return _progress(row) if row else None


def save_progress(cfg: Config, user_id: int, book_id: int, *, file_id: int, page: int, pages: int,
                  at: float | None = None) -> dict:
    at = time.time() if at is None else float(at)
    pages = max(1, int(pages))
    page = min(max(0, int(page)), pages - 1)
    position = min(1.0, max(0.0, page / max(1, pages - 1)))
    finished = page >= pages - 1
    with session(cfg.db_path) as con:
        con.execute(
            "INSERT INTO progress(user_id, book_id, file_id, page, pages, position, finished, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, book_id) DO UPDATE SET "
            "file_id = excluded.file_id, page = excluded.page, pages = excluded.pages, position = excluded.position, "
            "finished = excluded.finished, updated_at = excluded.updated_at "
            "WHERE excluded.updated_at >= progress.updated_at",
            (user_id, book_id, file_id, page, pages, position, int(finished), at))
    return get_progress(cfg, user_id, book_id)


def in_progress(cfg: Config, user_id: int, limit: int = 20) -> list[tuple[dict, dict]]:
    from .library import book_card

    with session(cfg.db_path) as con:
        rows = con.execute(
            "SELECT b.*, p.file_id AS p_file_id, p.page AS p_page, p.pages AS p_pages, p.position AS p_position, "
            "p.finished AS p_finished, p.updated_at AS p_updated_at FROM progress p JOIN books b ON b.id = p.book_id "
            "WHERE p.user_id = ? AND p.finished = 0 ORDER BY p.updated_at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [(book_card(r), {k: (bool(r[f"p_{k}"]) if k == "finished" else r[f"p_{k}"]) for k in PROGRESS_FIELDS})
            for r in rows]


def _bookmark(row) -> dict:
    return {"id": row["id"], "file_id": row["file_id"], "page": row["page"], "note": row["note"],
            "created_at": row["created_at"]}


def list_bookmarks(cfg: Config, user_id: int, book_id: int) -> list[dict]:
    with session(cfg.db_path) as con:
        return [_bookmark(r) for r in con.execute(
            "SELECT * FROM bookmarks WHERE user_id = ? AND book_id = ? ORDER BY page, id", (user_id, book_id))]


def add_bookmark(cfg: Config, user_id: int, book_id: int, *, file_id: int, page: int, note: str = "") -> dict:
    with session(cfg.db_path) as con:
        bid = con.execute("INSERT INTO bookmarks(user_id, book_id, file_id, page, note, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (user_id, book_id, file_id, max(0, int(page)), (note or "")[:500], time.time())).lastrowid
        return _bookmark(con.execute("SELECT * FROM bookmarks WHERE id = ?", (bid,)).fetchone())


def delete_bookmark(cfg: Config, user_id: int, bookmark_id: int) -> bool:
    with session(cfg.db_path) as con:
        return con.execute("DELETE FROM bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, user_id)).rowcount > 0

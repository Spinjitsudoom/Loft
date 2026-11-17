"""Talking about a book, without spoiling it. Each message is stamped with where its writer was
(their reading progress when they wrote it). A message from further into the book than the person
reading it is marked `ahead`, and the app blurs it until they get there (they can tap to read it
anyway). Nothing is hidden from its own writer, or from anyone who has finished the book.
One level of replies; writers edit or remove their own, admins remove any."""

from __future__ import annotations

import time

from .config import Config
from .db import session
from .notifications import notify

MAX_BODY = 4000
AHEAD_BY = 0.001  # rounding: the same page isn't "ahead"


def _where(con, user_id: int, book_id: int) -> tuple[float, str, bool]:
    """(position 0..1, a label like "Page 34" or "12%", finished) for someone's place in a book."""
    row = con.execute("SELECT page, position, finished, locator FROM progress WHERE user_id = ? AND book_id = ?",
                      (user_id, book_id)).fetchone()
    if row is None:
        return 0.0, "", False
    if row["finished"]:
        return 1.0, "Finished", True
    label = f"{round(row['position'] * 100)}%" if row["locator"] else f"Page {row['page'] + 1}"
    return float(row["position"]), label, False


def _body(text) -> str:
    if not isinstance(text, str):
        raise ValueError("A message must be text")
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").split("\n")]
    body = "\n".join(lines).strip()
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    if not body:
        raise ValueError("Write something first")
    if len(body) > MAX_BODY:
        raise ValueError(f"A message can be at most {MAX_BODY} characters")
    return body


def post(cfg: Config, user, book_id: int, text: str, parent_id: int | None = None) -> dict:
    body = _body(text)
    with session(cfg.db_path) as con:
        book = con.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            raise LookupError(book_id)
        answering = None
        if parent_id is not None:
            answering = con.execute("SELECT * FROM messages WHERE id = ? AND book_id = ?", (parent_id, book_id)).fetchone()
            if answering is None:
                raise LookupError(parent_id)
            parent_id = answering["parent_id"] or answering["id"]  # replies stay one level deep
        position, place, _ = _where(con, user.id, book_id)
        mid = con.execute("INSERT INTO messages(book_id, user_id, parent_id, body, position, place, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (book_id, user.id, parent_id, body, position, place, time.time())).lastrowid
        if answering is not None and answering["user_id"] not in (None, user.id):
            notify(con, [answering["user_id"]], "reply", f"{user.username} replied to you about “{book['title']}”",
                   f"#/book/{book_id}?discussion=1")
    return _one(cfg, user, mid)


def _message(row, viewer, mine_pos: float, finished: bool) -> dict:
    mine = row["user_id"] == viewer.id
    return {"id": row["id"], "parent_id": row["parent_id"], "by": row["by"], "mine": mine,
            "body": "" if row["removed"] else row["body"], "removed": bool(row["removed"]),
            "position": row["position"], "place": row["place"], "at": row["created_at"],
            "edited": row["edited_at"] is not None,
            "ahead": not mine and not finished and not row["removed"] and row["position"] > mine_pos + AHEAD_BY}


_SELECT = ("SELECT m.*, COALESCE(u.username, 'Someone who has left') AS by FROM messages m "
           "LEFT JOIN users u ON u.id = m.user_id ")


def thread(cfg: Config, viewer, book_id: int, after: int = 0) -> dict:
    """Every message about a book (or only those after `after`, to keep an open thread current)."""
    with session(cfg.db_path) as con:
        if con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone() is None:
            raise LookupError(book_id)
        position, place, finished = _where(con, viewer.id, book_id)
        rows = con.execute(_SELECT + "WHERE m.book_id = ? AND m.id > ? ORDER BY m.id", (book_id, after)).fetchall()
    return {"you": {"position": position, "place": place, "finished": finished},
            "messages": [_message(r, viewer, position, finished) for r in rows]}


def _one(cfg: Config, viewer, mid: int) -> dict:
    with session(cfg.db_path) as con:
        row = con.execute(_SELECT + "WHERE m.id = ?", (mid,)).fetchone()
        position, _, finished = _where(con, viewer.id, row["book_id"])
    return _message(row, viewer, position, finished)


def edit(cfg: Config, user, mid: int, text: str) -> dict:
    body = _body(text)
    with session(cfg.db_path) as con:
        if not con.execute("UPDATE messages SET body = ?, edited_at = ? WHERE id = ? AND user_id = ? AND removed = 0",
                           (body, time.time(), mid, user.id)).rowcount:
            raise LookupError(mid)
    return _one(cfg, user, mid)


def remove(cfg: Config, user, mid: int) -> None:
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        if row is None or not (user.admin or row["user_id"] == user.id):
            raise LookupError(mid)
        replies = con.execute("SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1", (mid,)).fetchone()
        if replies:  # the replies still make sense with a gap where it was
            con.execute("UPDATE messages SET removed = 1, body = '' WHERE id = ?", (mid,))
        else:
            con.execute("DELETE FROM messages WHERE id = ?", (mid,))
            parent = row["parent_id"]
            if parent and con.execute("SELECT removed FROM messages WHERE id = ?", (parent,)).fetchone()["removed"] \
                    and not con.execute("SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1", (parent,)).fetchone():
                con.execute("DELETE FROM messages WHERE id = ?", (parent,))  # a removed message with no replies left

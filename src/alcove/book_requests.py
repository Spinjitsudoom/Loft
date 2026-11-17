"""Asking for books. Anyone signed in asks for a title; others vote for it (the asker votes by
asking); the list is ranked by votes. An admin adds the book and links it (everyone who asked or
voted is told), or declines it with a reason."""

from __future__ import annotations

import time

from .config import Config
from .db import session
from .notifications import admins, notify

MAX_TITLE, MAX_AUTHOR, MAX_NOTE, MAX_REASON = 300, 200, 500, 500
MAX_OPEN_EACH = 30


def _text(value, most: int, what: str) -> str:
    value = " ".join((value or "").split()) if isinstance(value, str) or value is None else None
    if value is None:
        raise ValueError(f"The {what} must be text")
    if len(value) > most:
        raise ValueError(f"The {what} can be at most {most} characters")
    return value


def ask(cfg: Config, user, title: str, author: str = "", note: str = "") -> int:
    title = _text(title, MAX_TITLE, "title")
    if not title:
        raise ValueError("Say which book you’d like")
    author, note = _text(author, MAX_AUTHOR, "author"), _text(note, MAX_NOTE, "note")
    with session(cfg.db_path) as con:
        same = con.execute("SELECT id FROM requests WHERE status = 'open' AND title = ? COLLATE NOCASE", (title,)).fetchone()
        if same:
            raise ValueError("Someone has asked for that already: vote for it instead")
        if con.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status = 'open'",
                       (user.id,)).fetchone()[0] >= MAX_OPEN_EACH:
            raise ValueError(f"You have {MAX_OPEN_EACH} requests open already")
        rid = con.execute("INSERT INTO requests(user_id, title, author, note, created_at) VALUES (?, ?, ?, ?, ?)",
                          (user.id, title, author, note, time.time())).lastrowid
        con.execute("INSERT INTO request_votes(request_id, user_id) VALUES (?, ?)", (rid, user.id))
        notify(con, [a for a in admins(con) if a != user.id], "request", f"{user.username} asked for “{title}”",
               "#/add?tab=requests")
    return rid


def listing(cfg: Config, viewer_id: int, closed: bool = False) -> list[dict]:
    """Open requests, most wanted first; or (closed) the latest added or declined."""
    with session(cfg.db_path) as con:
        rows = con.execute(
            "SELECT r.*, COALESCE(u.username, 'Someone who has left') AS by, "
            "(SELECT COUNT(*) FROM request_votes v WHERE v.request_id = r.id) AS votes, "
            "EXISTS(SELECT 1 FROM request_votes v WHERE v.request_id = r.id AND v.user_id = ?) AS voted "
            "FROM requests r LEFT JOIN users u ON u.id = r.user_id "
            + ("WHERE r.status != 'open' ORDER BY r.decided_at DESC LIMIT 30" if closed
               else "WHERE r.status = 'open' ORDER BY votes DESC, r.created_at"),
            (viewer_id,)).fetchall()
    return [{"id": r["id"], "title": r["title"], "author": r["author"], "note": r["note"], "by": r["by"],
             "mine": r["user_id"] == viewer_id, "votes": r["votes"], "voted": bool(r["voted"]),
             "status": r["status"], "reason": r["reason"], "book_id": r["book_id"], "at": r["created_at"]}
            for r in rows]


def _open(con, rid: int):
    row = con.execute("SELECT * FROM requests WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise LookupError(rid)
    if row["status"] != "open":
        raise ValueError("That request has been dealt with already")
    return row


def vote(cfg: Config, user_id: int, rid: int, on: bool) -> None:
    with session(cfg.db_path) as con:
        _open(con, rid)
        if on:
            con.execute("INSERT OR IGNORE INTO request_votes(request_id, user_id) VALUES (?, ?)", (rid, user_id))
        else:
            con.execute("DELETE FROM request_votes WHERE request_id = ? AND user_id = ?", (rid, user_id))


def remove(cfg: Config, user, rid: int) -> None:
    """The asker takes back an open request (an admin can remove any)."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM requests WHERE id = ?", (rid,)).fetchone()
        if row is None or not (user.admin or row["user_id"] == user.id):
            raise LookupError(rid)
        con.execute("DELETE FROM requests WHERE id = ?", (rid,))


def _wanted_by(con, rid: int, asker) -> list[int]:
    return [asker] + [r["user_id"] for r in con.execute("SELECT user_id FROM request_votes WHERE request_id = ?", (rid,))]


def fulfil(cfg: Config, rid: int, book_id: int) -> None:
    with session(cfg.db_path) as con:
        row = _open(con, rid)
        book = con.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            raise LookupError(book_id)
        con.execute("UPDATE requests SET status = 'added', book_id = ?, decided_at = ? WHERE id = ?",
                    (book_id, time.time(), rid))
        notify(con, _wanted_by(con, rid, row["user_id"]), "request_added",
               f"“{book['title']}”, which you asked for, is in the library now", f"#/book/{book_id}")


def decline(cfg: Config, rid: int, reason: str = "") -> None:
    reason = _text(reason, MAX_REASON, "reason")
    with session(cfg.db_path) as con:
        row = _open(con, rid)
        con.execute("UPDATE requests SET status = 'declined', reason = ?, decided_at = ? WHERE id = ?",
                    (reason, time.time(), rid))
        notify(con, _wanted_by(con, rid, row["user_id"]), "request_declined",
               f"“{row['title']}” won’t be added" + (f": {reason}" if reason else ""), "#/add?tab=requests")

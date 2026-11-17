"""Members submitting books. A member uploads a file (uploads.py), fills in its details (title and
author at least) and sends it; it waits, outside the books folder, for an admin. The admin can
correct the details and cover, then approves (it's saved into the library as the admin's own
uploads are) or declines with a reason. The member is told either way. Nothing they send shows for
anyone else until it's approved."""

from __future__ import annotations

import json
import time

from . import uploads
from .config import Config
from .db import session
from .editing import FIELDS, clean_details
from .notifications import admins, notify

MAX_REASON = 500
MAX_WAITING_EACH = 25


def _row(r) -> dict:
    details = json.loads(r["details"])
    return {"id": r["id"], "token": r["token"], "filename": r["filename"], "format": r["format"],
            "title": details.get("title", ""), "details": details, "right_to_left": bool(r["right_to_left"]),
            "cover_url": r["cover_url"], "status": r["status"], "reason": r["reason"], "book_id": r["book_id"],
            "at": r["created_at"], "decided_at": r["decided_at"],
            **({"by": r["by"]} if "by" in r.keys() else {})}


def submit(cfg: Config, user, token: str, details: dict, *, cover_url: str | None = None,
           right_to_left: bool = False) -> int:
    uploads._draft(cfg, token, user)  # theirs, or LookupError
    info = uploads.draft_info(cfg, token)
    if info.get("submitted"):
        raise ValueError("That’s already been sent for approval")
    clean = clean_details({k: details.get(k) for k in FIELDS if k in details}, require=True)
    with session(cfg.db_path) as con:
        if con.execute("SELECT COUNT(*) FROM submissions WHERE user_id = ? AND status = 'waiting'",
                       (user.id,)).fetchone()[0] >= MAX_WAITING_EACH:
            raise ValueError(f"You have {MAX_WAITING_EACH} books waiting already; wait for some to be looked at")
        sid = con.execute(
            "INSERT INTO submissions(user_id, token, filename, format, details, right_to_left, cover_url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user.id, token, info["filename"], info["format"], json.dumps(clean), int(right_to_left), cover_url,
             time.time())).lastrowid
        notify(con, admins(con), "submission", f"{user.username} sent “{clean['title']}” for approval",
               "#/add?tab=approvals")
    uploads.mark_submitted(cfg, token)
    return sid


def mine(cfg: Config, user_id: int) -> list[dict]:
    with session(cfg.db_path) as con:
        return [_row(r) for r in con.execute("SELECT * FROM submissions WHERE user_id = ? ORDER BY id DESC LIMIT 100",
                                             (user_id,))]


def waiting(cfg: Config) -> list[dict]:
    with session(cfg.db_path) as con:
        return [_row(r) for r in con.execute(
            "SELECT s.*, COALESCE(u.username, 'Someone who has left') AS by FROM submissions s "
            "LEFT JOIN users u ON u.id = s.user_id WHERE s.status = 'waiting' ORDER BY s.id")]


def _waiting(con, sub_id: int):
    row = con.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    if row is None:
        raise LookupError(sub_id)
    if row["status"] != "waiting":
        raise ValueError("That’s been dealt with already")
    return row


def approve(cfg: Config, sub_id: int, details: dict | None = None, *, cover_url: str | None = None,
            right_to_left: bool | None = None) -> int:
    """Into the library, with the admin's corrections if they made any. Returns the new book's id."""
    with session(cfg.db_path) as con:
        row = _waiting(con, sub_id)
    book_id = uploads.save(cfg, row["token"], details if details is not None else json.loads(row["details"]),
                           cover_url=cover_url if cover_url is not None else row["cover_url"],
                           right_to_left=bool(row["right_to_left"]) if right_to_left is None else right_to_left,
                           approving=True)
    with session(cfg.db_path) as con:
        title = con.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()["title"]
        con.execute("UPDATE submissions SET status = 'approved', book_id = ?, decided_at = ? WHERE id = ?",
                    (book_id, time.time(), sub_id))
        notify(con, [row["user_id"]], "approved", f"“{title}”, which you sent, is in the library now", f"#/book/{book_id}")
    return book_id


def decline(cfg: Config, sub_id: int, reason: str = "") -> None:
    reason = " ".join((reason or "").split())
    if len(reason) > MAX_REASON:
        raise ValueError(f"The reason can be at most {MAX_REASON} characters")
    with session(cfg.db_path) as con:
        row = _waiting(con, sub_id)
        con.execute("UPDATE submissions SET status = 'declined', reason = ?, decided_at = ? WHERE id = ?",
                    (reason, time.time(), sub_id))
        title = json.loads(row["details"]).get("title", "")
        notify(con, [row["user_id"]], "declined",
               f"“{title}” wasn’t added" + (f": {reason}" if reason else ""), "#/add")
    try:
        uploads.discard(cfg, row["token"])
    except LookupError:
        pass


def withdraw(cfg: Config, user, sub_id: int) -> None:
    """The member takes back a book still waiting."""
    with session(cfg.db_path) as con:
        row = con.execute("SELECT * FROM submissions WHERE id = ? AND user_id = ?", (sub_id, user.id)).fetchone()
        if row is None:
            raise LookupError(sub_id)
        if row["status"] != "waiting":
            raise ValueError("That’s been dealt with already")
        con.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
    try:
        uploads.discard(cfg, row["token"])
    except LookupError:
        pass

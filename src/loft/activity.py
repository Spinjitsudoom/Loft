"""The activity log: what happened in the library, newest first, for admins.

Each entry says who (a person, or Loft itself), what (a kind and a short phrase such as "signed in"),
and which book, when there's one. The names are copied in as they were, so an entry still reads
right after the person or book is gone. Entries are kept for a year. Writing one never stands in
the way of what it records: if it can't be written, that goes to the server's own log instead.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager

from .config import Config
from .db import session

log = logging.getLogger(__name__)

GROUPS = {"sign_in": "Sign-ins", "people": "People", "books": "Books", "loans": "Loans", "ratings": "Ratings",
          "requests": "Requests", "discussion": "Discussion", "loft": "Loft"}
KEEP = 365 * 24 * 3600
TRIM_EVERY = 24 * 3600
TRIMMED = "activity_trimmed_at"


def record(con, kind: str, text: str, *, user_id: int | None = None, user_name: str = "",
           book_id: int | None = None, book_title: str = "", details: dict | None = None,
           at: float | None = None) -> None:
    """Add an entry. Missing names are looked up from the ids. Never raises."""
    try:
        now = time.time()
        if user_id is not None and not user_name:
            row = con.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            user_name = row[0] if row else ""
        if book_id is not None and not book_title:
            row = con.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
            book_title = row[0] if row else ""
        con.execute("INSERT INTO activity(at, user_id, user_name, kind, book_id, book_title, text, details) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (now if at is None else at, user_id, user_name, kind, book_id, book_title, text,
                     json.dumps(details) if details else None))
        trim(con, now)
    except Exception:
        log.exception("Couldn’t write to the activity log (%s: %s)", kind, text)


@contextmanager
def writing(cfg: Config):
    """A short session for writing entries, for callers without one of their own. Whatever goes
    wrong inside it (looking up a name for the entry, say) goes to the server's log, never further."""
    try:
        with session(cfg.db_path) as con:
            yield con
    except Exception:
        log.exception("Couldn’t write to the activity log")


def note(cfg: Config, kind: str, text: str, **kw) -> None:
    """record() in a short session of its own. Never raises."""
    with writing(cfg) as con:
        record(con, kind, text, **kw)


def trim(con, now: float) -> int:
    """Remove entries over a year old; does the work at most once a day."""
    row = con.execute("SELECT value FROM meta WHERE key = ?", (TRIMMED,)).fetchone()
    if row and now - float(row[0]) < TRIM_EVERY:
        return 0
    removed = con.execute("DELETE FROM activity WHERE at < ?", (now - KEEP,)).rowcount
    con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (TRIMMED, str(now)))
    return removed


def listing(cfg: Config, *, before: int | None = None, user_id: int | None = None, group: str | None = None,
            limit: int = 50) -> dict:
    """A page of entries, newest first; `before` is the id of the last entry already shown."""
    where, args = [], []
    if before is not None:
        where.append("a.id < ?")
        args.append(before)
    if user_id is not None:
        where.append("a.user_id = ?")
        args.append(user_id)
    if group in GROUPS:
        where.append("a.kind LIKE ?")
        args.append(f"{group}.%")
    sql = ("SELECT a.*, u.id IS NOT NULL AS user_exists, b.id IS NOT NULL AS book_exists FROM activity a "
           "LEFT JOIN users u ON u.id = a.user_id LEFT JOIN books b ON b.id = a.book_id"
           + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY a.id DESC LIMIT ?")
    with session(cfg.db_path) as con:
        rows = con.execute(sql, (*args, limit + 1)).fetchall()
        people = [{"id": r["id"], "name": r["username"]}
                  for r in con.execute("SELECT id, username FROM users ORDER BY username COLLATE NOCASE")]
    return {"entries": [_entry(r) for r in rows[:limit]], "more": len(rows) > limit, "people": people,
            "groups": GROUPS}


def _entry(r) -> dict:
    return {
        "id": r["id"], "at": r["at"], "kind": r["kind"], "group": r["kind"].split(".", 1)[0], "text": r["text"],
        "user": {"id": r["user_id"], "name": r["user_name"], "exists": bool(r["user_exists"])}
        if r["user_id"] is not None or r["user_name"] else None,
        "book": {"id": r["book_id"], "title": r["book_title"], "exists": bool(r["book_exists"])}
        if r["book_id"] is not None else None,
        "details": json.loads(r["details"]) if r["details"] else None,
    }

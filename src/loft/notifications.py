"""In-app notifications: a request was added, a submission approved or declined, a reply, and
(for admins) someone asking to join, a new submission or request. Each person sees only theirs."""

from __future__ import annotations

import time
from collections.abc import Iterable

from .config import Config
from .db import session

KEEP = 200  # the newest kept per person; older ones go


def admins(con) -> list[int]:
    return [r["id"] for r in con.execute("SELECT id FROM users WHERE admin = 1")]


def notify(con, user_ids: Iterable[int], kind: str, text: str, link: str = "") -> None:
    """Tell these people something, inside the caller's transaction."""
    now = time.time()
    for uid in dict.fromkeys(u for u in user_ids if u is not None):
        con.execute("INSERT INTO notifications(user_id, kind, text, link, created_at) VALUES (?, ?, ?, ?, ?)",
                    (uid, kind, text, link, now))
        con.execute("DELETE FROM notifications WHERE user_id = ? AND id NOT IN "
                    "(SELECT id FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?)", (uid, uid, KEEP))


def list_for(cfg: Config, user_id: int, limit: int = 50) -> dict:
    with session(cfg.db_path) as con:
        rows = con.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                           (user_id, limit)).fetchall()
        unread = con.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                             (user_id,)).fetchone()[0]
    return {"unread": unread, "items": [{"id": r["id"], "kind": r["kind"], "text": r["text"], "link": r["link"],
                                         "at": r["created_at"], "read": r["read_at"] is not None} for r in rows]}


def mark_read(cfg: Config, user_id: int) -> None:
    with session(cfg.db_path) as con:
        con.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (time.time(), user_id))

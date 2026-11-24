"""Ratings: each person gives a book one to five whole stars. Everyone sees the average and how many
rated; only you see your own stars (admins see who rated what in the activity log)."""

from __future__ import annotations

import time

from . import activity
from .config import Config
from .db import session


def _check(stars) -> int | None:
    if stars is None:
        return None
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        raise ValueError("A rating is a whole number of stars from 1 to 5")
    return stars


def summary(con, book_id: int, user_id: int | None) -> dict:
    """{"mine", "average", "count"}: your stars (None if you haven't rated it), and everyone's."""
    average, count = con.execute("SELECT AVG(stars), COUNT(*) FROM ratings WHERE book_id = ?", (book_id,)).fetchone()
    mine = con.execute("SELECT stars FROM ratings WHERE user_id = ? AND book_id = ?",
                       (user_id, book_id)).fetchone() if user_id is not None else None
    return {"mine": mine[0] if mine else None, "average": round(average, 1) if count else None, "count": count}


def rate(cfg: Config, user_id: int, book_id: int, stars: int | None) -> dict:
    """Set this person's rating for a book; None clears it. Returns the summary."""
    stars = _check(stars)
    with session(cfg.db_path) as con:
        if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
            raise LookupError(book_id)
        if stars is None:
            if con.execute("DELETE FROM ratings WHERE user_id = ? AND book_id = ?", (user_id, book_id)).rowcount:
                activity.record(con, "ratings.cleared", "cleared their rating of", user_id=user_id, book_id=book_id)
        else:
            con.execute("INSERT INTO ratings(user_id, book_id, stars, rated_at) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(user_id, book_id) DO UPDATE SET stars = excluded.stars, rated_at = excluded.rated_at",
                        (user_id, book_id, stars, time.time()))
            activity.record(con, "ratings.rated", "rated", user_id=user_id, book_id=book_id,
                            details={"stars": stars, "after": "★" * stars + "☆" * (5 - stars)})
        return summary(con, book_id, user_id)

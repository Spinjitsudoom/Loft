"""Checking out and returning, as a library does, kept in step with reading.

A book you're reading is checked out to you: opening it to read (when the reader saves your place),
setting it to Reading or Incomplete by hand, or the Check out button. It comes back when you finish it
("finished"), when it's abandoned ("abandoned"), or when you return it or set it to Not started or
Want to read ("returned"). Checking out never locks: everyone can still read the book.

Like reading statuses, nothing runs in the background. A loan quiet for statuses.ABANDONED_AFTER is
closed as abandoned when loans are next looked at (settle), dated when it became abandoned. The
database keeps one open loan per person and book (the partial unique index loans_open).
"""

from __future__ import annotations

import time

from . import activity, statuses
from .config import Config
from .db import session

HOWS = {"finished": "returned (finished)", "abandoned": "returned (abandoned)", "returned": "returned early"}
FILLED_IN = "loans_filled_in"


def out(con, user_id: int, book_id: int, at: float) -> bool:
    """Check the book out to this person, unless it already is. Says whether it opened a loan."""
    opened = con.execute("INSERT INTO loans(user_id, book_id, out_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(user_id, book_id) WHERE returned_at IS NULL DO NOTHING",
                         (user_id, book_id, at)).rowcount > 0
    if opened:
        activity.record(con, "loans.out", "checked out", user_id=user_id, book_id=book_id, at=at)
    return opened


def back(con, user_id: int, book_id: int, how: str, at: float) -> bool:
    """Close this person's open loan of the book, if there is one; how is a key of HOWS."""
    if how not in HOWS:
        raise ValueError(how)
    closed = con.execute("UPDATE loans SET returned_at = MAX(?, out_at), how = ? "
                         "WHERE user_id = ? AND book_id = ? AND returned_at IS NULL",
                         (at, how, user_id, book_id)).rowcount > 0
    if closed:
        activity.record(con, "loans.returned", HOWS[how], user_id=user_id, book_id=book_id, at=at)
    return closed


def reading(con, user_id: int, book_id: int, at: float, finished: bool) -> None:
    """The reader saved a place (and it was kept). The last page returns the book; any other page checks
    it out, when that reading is what decides the status (not a later status set by hand)."""
    if finished:
        back(con, user_id, book_id, "finished", at)
    elif statuses.status_for(con, user_id, book_id, now=at) == "reading":
        out(con, user_id, book_id, at)


def marked(con, user_id: int, book_id: int, status: str, at: float) -> None:
    """A status was set by hand: Reading and Incomplete check the book out, the others return it."""
    if status in ("reading", "incomplete"):
        out(con, user_id, book_id, at)
    elif status in ("finished", "abandoned"):
        back(con, user_id, book_id, status, at)
    else:   # unread, want
        back(con, user_id, book_id, "returned", at)


def settle(con, user_id: int | None, now: float) -> int:
    """Close the open loans (this person's, or everyone's for None) that have been quiet for
    ABANDONED_AFTER, as abandoned, when they became so. Quiet starts at the latest of: when the loan
    went out, the last reading, and Reading or Incomplete set by hand. Returns how many it closed."""
    rows = con.execute(
        "SELECT l.user_id, l.book_id, MAX(l.out_at, COALESCE(p.updated_at, 0), "
        "COALESCE(CASE WHEN s.status IN ('reading', 'incomplete') THEN s.set_at END, 0)) AS quiet "
        "FROM loans l LEFT JOIN progress p ON p.user_id = l.user_id AND p.book_id = l.book_id "
        "LEFT JOIN book_status s ON s.user_id = l.user_id AND s.book_id = l.book_id "
        "WHERE l.returned_at IS NULL AND (? IS NULL OR l.user_id = ?)", (user_id, user_id)).fetchall()
    closed = 0
    for r in rows:
        if now - r["quiet"] >= statuses.ABANDONED_AFTER:
            closed += back(con, r["user_id"], r["book_id"], "abandoned", r["quiet"] + statuses.ABANDONED_AFTER)
    return closed


def _book(con, book_id: int) -> None:
    if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
        raise LookupError(book_id)


def loan_for(con, viewer_id: int | None, book_id: int) -> dict:
    """{"mine": {"out_at"} | None, "others": [the names of everyone else with it out]}."""
    settle(con, None, time.time())
    mine = None
    others = []
    for r in con.execute("SELECT l.user_id, l.out_at, u.username FROM loans l JOIN users u ON u.id = l.user_id "
                         "WHERE l.book_id = ? AND l.returned_at IS NULL ORDER BY u.username COLLATE NOCASE",
                         (book_id,)):
        if r["user_id"] == viewer_id:
            mine = {"out_at": r["out_at"]}
        else:
            others.append(r["username"])
    return {"mine": mine, "others": others}


def check_out(cfg: Config, user_id: int, book_id: int) -> dict:
    """The Check out button."""
    now = time.time()
    with session(cfg.db_path) as con:
        _book(con, book_id)
        settle(con, user_id, now)
        out(con, user_id, book_id, now)
        return loan_for(con, user_id, book_id)


def give_back(cfg: Config, user_id: int, book_id: int) -> dict:
    """The Return button: ends the loan, leaving the place and reading status as they are."""
    now = time.time()
    with session(cfg.db_path) as con:
        _book(con, book_id)
        settle(con, user_id, now)
        back(con, user_id, book_id, "returned", now)
        return loan_for(con, user_id, book_id)


def card(cfg: Config, user_id: int) -> dict:
    """This person's library card: what's out now (oldest first) and everything returned (newest first)."""
    from .library import book_card

    with session(cfg.db_path) as con:
        settle(con, user_id, time.time())
        rows = con.execute("SELECT b.*, l.out_at AS loan_out, l.returned_at AS loan_back, l.how AS loan_how "
                           "FROM loans l JOIN books b ON b.id = l.book_id WHERE l.user_id = ? "
                           "ORDER BY l.out_at, l.id", (user_id,)).fetchall()
    out_now = [{**book_card(r), "out_at": r["loan_out"]} for r in rows if r["loan_back"] is None]
    returned = sorted(({**book_card(r), "out_at": r["loan_out"], "returned_at": r["loan_back"], "how": r["loan_how"]}
                       for r in rows if r["loan_back"] is not None), key=lambda b: -b["returned_at"])
    return {"out": out_now, "returned": returned}


def out_now(cfg: Config) -> list[dict]:
    """Every book checked out now: [{"book", "people", "since"}], the longest out first."""
    from .library import book_card

    books: dict[int, dict] = {}
    with session(cfg.db_path) as con:
        settle(con, None, time.time())
        for r in con.execute("SELECT b.*, l.out_at AS loan_out, u.username AS loan_by FROM loans l "
                             "JOIN books b ON b.id = l.book_id JOIN users u ON u.id = l.user_id "
                             "WHERE l.returned_at IS NULL ORDER BY l.out_at, l.id"):
            entry = books.setdefault(r["id"], {"book": book_card(r), "people": [], "since": r["loan_out"]})
            entry["people"].append(r["loan_by"])
    for entry in books.values():
        entry["people"].sort(key=str.casefold)
    return list(books.values())


def fill_in(cfg: Config) -> int:
    """Once, on upgrading to loans: every book someone is reading (Reading or Incomplete) is checked out
    to them, from that reading. Finished and abandoned books get no history. Not logged."""
    filled = 0
    with session(cfg.db_path) as con:
        if con.execute("SELECT 1 FROM meta WHERE key = ?", (FILLED_IN,)).fetchone():
            return 0
        now = time.time()
        for (user_id,) in con.execute("SELECT id FROM users").fetchall():
            for book_id, (status, since) in statuses.statuses_for(con, user_id, now).items():
                if status in ("reading", "incomplete"):
                    filled += con.execute("INSERT INTO loans(user_id, book_id, out_at) VALUES (?, ?, ?) "
                                          "ON CONFLICT(user_id, book_id) WHERE returned_at IS NULL DO NOTHING",
                                          (user_id, book_id, since)).rowcount
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (FILLED_IN, str(now)))
    return filled

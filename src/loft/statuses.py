"""Each person's reading status for each book: Want to read, Not started, Reading, Incomplete,
Abandoned or Finished.

Nothing runs in the background: a status is worked out when it's asked for, from three times: the
last reading (progress), the last status set by hand (book_status), and when the book went on Want to
read (the shelf). The latest decides. A book being read turns Incomplete after 15 days without reading
and Abandoned after 30; reaching the last page finishes it. A status set by hand holds until the book
is read again, except that Reading and Incomplete set by hand age as reading does, from when they were
set. Want to read is only ever set by hand: it's the Want to read shelf, which reading takes a book off.
"""

from __future__ import annotations

import time

from .config import Config
from .db import session

DAY = 24 * 3600
INCOMPLETE_AFTER = 15 * DAY
ABANDONED_AFTER = 30 * DAY

STATUSES = ("want", "unread", "reading", "incomplete", "abandoned", "finished")
MARKS = ("unread", "reading", "incomplete", "abandoned", "finished")   # the ones kept in book_status
LABELS = {"want": "Want to read", "unread": "Not started", "reading": "Reading", "incomplete": "Incomplete",
          "abandoned": "Abandoned", "finished": "Finished"}


def _aged(since: float, now: float) -> str:
    quiet = now - since
    return "abandoned" if quiet >= ABANDONED_AFTER else "incomplete" if quiet >= INCOMPLETE_AFTER else "reading"


def status_of(*, read_at: float | None, finished: bool, mark: str | None, mark_at: float | None,
              want_at: float | None, now: float) -> str:
    """The status from the three events; the latest wins (at the same time: a mark, then want, then reading)."""
    events = [(t, rank, kind) for t, rank, kind in ((mark_at if mark else None, 2, "mark"), (want_at, 1, "want"),
                                                    (read_at, 0, "read")) if t is not None]
    if not events:
        return "unread"
    _, _, kind = max(events)
    if kind == "want":
        return "want"
    if kind == "mark":
        if mark == "reading":
            return _aged(mark_at, now)
        if mark == "incomplete":
            return "abandoned" if now - mark_at >= ABANDONED_AFTER else "incomplete"
        return mark
    return "finished" if finished else _aged(read_at, now)


def _events(con, user_id: int, book_id: int | None = None) -> dict[int, dict]:
    only, args = ("AND book_id = ?", (user_id, book_id)) if book_id is not None else ("", (user_id,))
    books: dict[int, dict] = {}
    for r in con.execute(f"SELECT book_id, updated_at, finished FROM progress WHERE user_id = ? {only}", args):
        books.setdefault(r["book_id"], {}).update(read_at=r["updated_at"], finished=bool(r["finished"]))
    for r in con.execute(f"SELECT book_id, status, set_at FROM book_status WHERE user_id = ? {only}", args):
        books.setdefault(r["book_id"], {}).update(mark=r["status"], mark_at=r["set_at"])
    for r in con.execute(
            "SELECT sb.book_id, sb.added_at FROM shelf_books sb JOIN shelves s ON s.id = sb.shelf_id "
            f"WHERE s.user_id = ? AND s.kind = 'want' {only.replace('book_id', 'sb.book_id')}", args):
        books.setdefault(r["book_id"], {}).update(want_at=r["added_at"])
    return books


def _decide(e: dict, now: float) -> tuple[str, float]:
    s = status_of(read_at=e.get("read_at"), finished=e.get("finished", False), mark=e.get("mark"),
                  mark_at=e.get("mark_at"), want_at=e.get("want_at"), now=now)
    since = max(t for t in (e.get("read_at"), e.get("mark_at"), e.get("want_at")) if t is not None)
    return s, since


def statuses_for(con, user_id: int, now: float | None = None) -> dict[int, tuple[str, float]]:
    """Book id → (status, when its latest event was), for every book this person has a status for.
    Books that aren't here are Not started."""
    now = time.time() if now is None else now
    return {bid: _decide(e, now) for bid, e in _events(con, user_id).items()}


def status_for(con, user_id: int, book_id: int, now: float | None = None) -> str:
    e = _events(con, user_id, book_id).get(book_id)
    return _decide(e, time.time() if now is None else now)[0] if e else "unread"


def _want_shelf(con, user_id: int) -> int:
    from .shelves import _ensure_want

    _ensure_want(con, user_id)
    return con.execute("SELECT id FROM shelves WHERE user_id = ? AND kind = 'want'", (user_id,)).fetchone()[0]


def _answer(con, user_id: int, book_id: int) -> dict:
    shelves = [r[0] for r in con.execute(
        "SELECT s.id FROM shelf_books sb JOIN shelves s ON s.id = sb.shelf_id WHERE s.user_id = ? AND sb.book_id = ? "
        "ORDER BY s.kind = 'own', s.name COLLATE NOCASE", (user_id, book_id))]
    return {"status": status_for(con, user_id, book_id), "shelves": shelves}


def _book(con, book_id: int) -> None:
    if not con.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
        raise LookupError(book_id)


def get_status(cfg: Config, user_id: int, book_id: int) -> dict:
    """{"status", "shelves"} for one book (the shelves too, as Want to read is one)."""
    with session(cfg.db_path) as con:
        _book(con, book_id)
        return _answer(con, user_id, book_id)


def set_status(cfg: Config, user_id: int, book_id: int, status: str, at: float | None = None) -> dict:
    """Set a book's status by hand. Want to read puts it on that shelf; anything else takes it off."""
    if status not in STATUSES:
        raise ValueError(f"A reading status is one of: {', '.join(LABELS.values())}")
    at = time.time() if at is None else at
    with session(cfg.db_path) as con:
        _book(con, book_id)
        want = _want_shelf(con, user_id)
        if status == "want":
            con.execute("DELETE FROM book_status WHERE user_id = ? AND book_id = ?", (user_id, book_id))
            con.execute("INSERT INTO shelf_books(shelf_id, book_id, added_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(shelf_id, book_id) DO UPDATE SET added_at = excluded.added_at", (want, book_id, at))
        else:
            con.execute("INSERT INTO book_status(user_id, book_id, status, set_at) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(user_id, book_id) DO UPDATE SET status = excluded.status, set_at = excluded.set_at",
                        (user_id, book_id, status, at))
            con.execute("DELETE FROM shelf_books WHERE shelf_id = ? AND book_id = ?", (want, book_id))
        return _answer(con, user_id, book_id)


def opened(cfg: Config, user_id: int, book_id: int) -> dict:
    """The reader opened this book: one that had stopped (Incomplete, Abandoned) is Reading again, even
    before a page is turned. Its place is untouched. Others stay as they are (a look inside a finished
    book doesn't unfinish it; a peek at one not started doesn't start it)."""
    with session(cfg.db_path) as con:
        _book(con, book_id)
        if status_for(con, user_id, book_id) in ("incomplete", "abandoned"):
            con.execute("INSERT INTO book_status(user_id, book_id, status, set_at) VALUES (?, ?, 'reading', ?) "
                        "ON CONFLICT(user_id, book_id) DO UPDATE SET status = excluded.status, set_at = excluded.set_at",
                        (user_id, book_id, time.time()))
        return _answer(con, user_id, book_id)


def read_now(con, user_id: int, book_id: int, at: float) -> None:
    """Reading a book takes it off Want to read (unless it went on after this reading)."""
    con.execute("DELETE FROM shelf_books WHERE book_id = ? AND added_at <= ? AND shelf_id IN "
                "(SELECT id FROM shelves WHERE user_id = ? AND kind = 'want')", (book_id, at, user_id))

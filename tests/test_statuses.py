"""Reading status: worked out from reading, ageing by itself, and set by hand."""
import time

import pytest

from loft import auth, library, reading, shelves, statuses
from loft.db import session

DAY = 24 * 3600
NOW = 1_800_000_000.0


@pytest.fixture
def ann(cfg):
    return auth.create_user(cfg, "ann", "annannann", admin=True)


def _file(cfg, book):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE book_id = ?", (book,)).fetchone()["id"]


def read(cfg, user, book, ago=0.0, page=3, pages=100):
    reading.save_progress(cfg, user.id, book, file_id=_file(cfg, book), page=page, pages=pages,
                          at=time.time() - ago)


def status(cfg, user, book):
    with session(cfg.db_path) as con:
        return statuses.status_for(con, user.id, book)


def want_id(cfg, user):
    return next(s["id"] for s in shelves.list_shelves(cfg, user.id) if s["kind"] == "want")


def test_status_of():
    def of(read_at=None, finished=False, mark=None, mark_at=None, want_at=None):
        return statuses.status_of(read_at=read_at, finished=finished, mark=mark, mark_at=mark_at,
                                  want_at=want_at, now=NOW)

    assert of() == "unread"
    assert of(read_at=NOW) == "reading"
    assert of(read_at=NOW - 15 * DAY + 1) == "reading"
    assert of(read_at=NOW - 15 * DAY) == "incomplete"
    assert of(read_at=NOW - 30 * DAY + 1) == "incomplete"
    assert of(read_at=NOW - 30 * DAY) == "abandoned"
    assert of(read_at=NOW - 60 * DAY, finished=True) == "finished"
    assert of(read_at=NOW - DAY, mark="abandoned", mark_at=NOW - 10) == "abandoned"
    assert of(read_at=NOW - 5, mark="abandoned", mark_at=NOW - DAY) == "reading"      # read again since
    assert of(read_at=NOW - 40 * DAY, mark="reading", mark_at=NOW - 16 * DAY) == "incomplete"
    assert of(mark="incomplete", mark_at=NOW - 29 * DAY) == "incomplete"
    assert of(mark="incomplete", mark_at=NOW - 30 * DAY) == "abandoned"
    assert of(mark="finished", mark_at=NOW - 90 * DAY) == "finished"
    assert of(mark="unread", mark_at=NOW - 90 * DAY, read_at=NOW - 91 * DAY) == "unread"
    assert of(read_at=NOW - DAY, want_at=NOW - 10) == "want"
    assert of(read_at=NOW - 10, want_at=NOW - DAY) == "reading"
    assert of(read_at=NOW - 10, mark="abandoned", mark_at=NOW - 10) == "abandoned"   # a tie: the mark
    assert of(want_at=NOW - 10, mark="finished", mark_at=NOW - 10) == "finished"


def test_reading_ages(cfg, ann, add):
    a, b, c = add("Gyo"), add("Uzumaki"), add("Tomie")
    read(cfg, ann, a, ago=16 * DAY)
    read(cfg, ann, b, ago=31 * DAY)
    read(cfg, ann, c, page=99)
    assert (status(cfg, ann, a), status(cfg, ann, b), status(cfg, ann, c)) == ("incomplete", "abandoned", "finished")
    assert status(cfg, ann, add("Never opened")) == "unread"


def test_set_by_hand_holds_until_read_again(cfg, ann, add):
    book = add("Gyo")
    read(cfg, ann, book, ago=DAY)
    assert statuses.set_status(cfg, ann.id, book, "abandoned")["status"] == "abandoned"
    read(cfg, ann, book, ago=60)            # a phone back online, with a reading from before the mark
    assert status(cfg, ann, book) == "abandoned"
    read(cfg, ann, book, ago=-1)
    assert status(cfg, ann, book) == "reading"


def test_want_to_read(cfg, ann, add):
    book = add("Gyo")
    want = want_id(cfg, ann)
    got = statuses.set_status(cfg, ann.id, book, "want")
    assert got == {"status": "want", "shelves": [want]}
    assert shelves.for_book(cfg, ann.id, book) == [want]
    read(cfg, ann, book, ago=-1)
    assert status(cfg, ann, book) == "reading" and shelves.for_book(cfg, ann.id, book) == []
    assert statuses.set_status(cfg, ann.id, book, "want", at=time.time() + 5)["status"] == "want"
    assert statuses.set_status(cfg, ann.id, book, "finished", at=time.time() + 10) == {"status": "finished", "shelves": []}
    other = add("Uzumaki")
    shelves.add(cfg, ann.id, want, other)
    assert status(cfg, ann, other) == "want"
    assert statuses.get_status(cfg, ann.id, other) == {"status": "want", "shelves": [want]}


def test_set_status_errors(cfg, ann, add):
    book = add("Gyo")
    with pytest.raises(ValueError):
        statuses.set_status(cfg, ann.id, book, "skimmed")
    with pytest.raises(LookupError):
        statuses.set_status(cfg, ann.id, 99999, "finished")
    with pytest.raises(LookupError):
        statuses.get_status(cfg, ann.id, 99999)


def test_statuses_are_each_persons_own(cfg, ann, add):
    sam = auth.create_user(cfg, "sam", "samsamsam")
    book = add("Gyo")
    statuses.set_status(cfg, ann.id, book, "abandoned")
    assert status(cfg, sam, book) == "unread"


def test_merge_keeps_marks(cfg, ann, add):
    into, other, a, b = add("Gyo"), add("Gyo (copy)"), add("Tomie"), add("Tomie (copy)")
    statuses.set_status(cfg, ann.id, other, "abandoned")
    library.merge_books(cfg, into, other)
    assert status(cfg, ann, into) == "abandoned"
    statuses.set_status(cfg, ann.id, a, "finished", at=time.time() + 10)
    statuses.set_status(cfg, ann.id, b, "abandoned", at=time.time() + 20)
    library.merge_books(cfg, a, b)
    assert status(cfg, ann, a) == "abandoned"


def test_home_rows(cfg, ann, add):
    now_, hours, twenty, forty, done, marked = (add(t) for t in ("Now", "Hours", "Twenty", "Forty", "Done", "Marked"))
    read(cfg, ann, hours, ago=2 * 3600)
    read(cfg, ann, now_, ago=-1)
    read(cfg, ann, twenty, ago=20 * DAY)
    read(cfg, ann, forty, ago=40 * DAY)
    read(cfg, ann, done, page=99, ago=DAY)
    read(cfg, ann, marked, ago=DAY)
    statuses.set_status(cfg, ann.id, marked, "finished")
    home = library.home(cfg, ann)
    assert home["hero_kind"] == "continue" and home["hero"]["id"] == now_
    rows = {r["title"]: [b["id"] for b in r["books"]] for r in home["rows"]}
    assert rows["Continue reading"] == [now_, hours]
    assert rows["Incomplete"] == [twenty]
    assert sorted(rows["Finished"]) == sorted([done, marked])
    incomplete = next(r for r in home["rows"] if r["title"] == "Incomplete")
    assert (incomplete["kind"], incomplete["value"]) == ("status", "incomplete")
    listed = library.list_books(cfg, kind="status", value="abandoned", user=ann)
    assert [b["id"] for b in listed["books"]] == [forty] and listed["total"] == 1
    assert {b["id"] for b in library.list_books(cfg, kind="finished", value="", user=ann)["books"]} == {done, marked}
    with pytest.raises(ValueError):
        library.list_books(cfg, kind="status", value="nope", user=ann)
    assert library.get_book(cfg, twenty, ann)["status"] == "incomplete"


def test_set_to_reading_by_hand_is_continued(cfg, ann, add):
    """Review: a book set to Reading by hand (a re-read, or never opened) is in Continue reading, newest first."""
    reread, fresh, old, other = add("Reread"), add("Fresh"), add("Old"), add("Other")
    read(cfg, ann, reread, page=99, ago=5 * DAY)
    read(cfg, ann, old, ago=40 * DAY)
    read(cfg, ann, other, ago=3600)
    statuses.set_status(cfg, ann.id, reread, "reading", at=time.time() - 60)
    statuses.set_status(cfg, ann.id, fresh, "reading", at=time.time() - 50)
    statuses.set_status(cfg, ann.id, old, "reading", at=time.time() - 40)
    got = [(card["id"], p and p["page"]) for card, p in reading.in_progress(cfg, ann.id)]
    assert got == [(old, 3), (fresh, None), (reread, None), (other, 3)]   # a finished place isn't continued
    assert library.home(cfg, ann)["hero"]["id"] == old


def test_opening_a_stopped_book_makes_it_reading(cfg, ann, add):
    """Review: opening an Incomplete or Abandoned book in the reader makes it Reading, without a page turned."""
    stopped, quit_, finished, fresh = add("Stopped"), add("Quit"), add("Finished"), add("Fresh")
    read(cfg, ann, stopped, ago=20 * DAY)
    statuses.set_status(cfg, ann.id, quit_, "abandoned")
    read(cfg, ann, finished, page=99, ago=DAY)
    for book in (stopped, quit_, finished, fresh):
        statuses.opened(cfg, ann.id, book)
    assert [status(cfg, ann, b) for b in (stopped, quit_, finished, fresh)] == ["reading", "reading", "finished", "unread"]
    assert reading.get_progress(cfg, ann.id, stopped)["page"] == 3   # its place is untouched

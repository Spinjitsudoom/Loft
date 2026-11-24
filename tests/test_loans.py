"""Checking out and returning, kept in step with reading (src/loft/loans.py)."""
import threading
import time

import pytest

from loft import activity, auth, library, loans, reading, statuses
from loft.db import session

DAY = 24 * 3600
MONTH = statuses.ABANDONED_AFTER


@pytest.fixture
def ann(cfg):
    return auth.create_user(cfg, "ann", "annannann", admin=True)


@pytest.fixture
def ben(cfg):
    return auth.create_user(cfg, "ben", "benbenben")


def _file(cfg, book):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE book_id = ?", (book,)).fetchone()["id"]


def read(cfg, user, book, page, pages=10, at=None):
    return reading.save_progress(cfg, user.id, book, file_id=_file(cfg, book), page=page, pages=pages, at=at)


def rows(cfg, user=None, book=None):
    with session(cfg.db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM loans WHERE (? IS NULL OR user_id = ?) AND (? IS NULL OR book_id = ?) ORDER BY id",
            (user and user.id, user and user.id, book, book))]


def open_loans(cfg, user=None, book=None):
    return [r for r in rows(cfg, user, book) if r["returned_at"] is None]


def loan_for(cfg, user, book):
    with session(cfg.db_path) as con:
        return loans.loan_for(con, user.id, book)


def settle(cfg, user, now):
    with session(cfg.db_path) as con:
        return loans.settle(con, user and user.id, now)


def status(cfg, user, book):
    with session(cfg.db_path) as con:
        return statuses.status_for(con, user.id, book)


def loan_entries(cfg):
    return [e for e in activity.listing(cfg)["entries"] if e["group"] == "loans"]


def test_reading_checks_out_and_the_last_page_returns(cfg, add, ann):
    book = add("Tide Line")
    read(cfg, ann, book, 3)
    [loan] = rows(cfg, ann, book)
    assert loan["returned_at"] is None and loan["how"] is None
    read(cfg, ann, book, 4)
    assert len(rows(cfg)) == 1                                   # still the same loan
    read(cfg, ann, book, 9)
    [loan] = rows(cfg, ann, book)
    assert loan["how"] == "finished" and loan["returned_at"] is not None
    assert [(e["kind"], e["text"]) for e in loan_entries(cfg)] == [("loans.returned", "returned (finished)"),
                                                                  ("loans.out", "checked out")]
    assert loan_for(cfg, ann, book) == {"mine": None, "others": []}


def test_a_finished_book_read_again(cfg, add, ann):
    book = add("Tide Line")
    read(cfg, ann, book, 3)
    read(cfg, ann, book, 9)
    for _ in range(3):
        read(cfg, ann, book, 9)                                  # the last page saved again
    assert len(rows(cfg)) == 1 and len(loan_entries(cfg)) == 2
    read(cfg, ann, book, 2)                                      # turned back: read again
    assert len(open_loans(cfg, ann, book)) == 1
    card = loans.card(cfg, ann.id)
    assert [b["id"] for b in card["out"]] == [book] and [b["id"] for b in card["returned"]] == [book]


def test_a_late_save_from_another_device_doesnt_reopen_it(cfg, add, ann):
    book = add("Tide Line")
    now = time.time()
    read(cfg, ann, book, 3, at=now - 100)
    read(cfg, ann, book, 9, at=now - 10)
    read(cfg, ann, book, 5, at=now - 50)                         # older than what's kept: ignored
    assert open_loans(cfg) == [] and len(rows(cfg)) == 1


def test_thirty_quiet_days_return_it_as_abandoned(cfg, add, ann):
    book = add("Tide Line")
    t = time.time()
    read(cfg, ann, book, 3, at=t)
    assert settle(cfg, ann, t + MONTH - 1) == 0
    assert settle(cfg, None, t + MONTH + 1) == 1
    [loan] = rows(cfg)
    assert loan["how"] == "abandoned" and loan["returned_at"] == t + MONTH
    entry = loan_entries(cfg)[0]
    assert (entry["kind"], entry["text"], entry["at"]) == ("loans.returned", "returned (abandoned)", t + MONTH)
    assert settle(cfg, None, t + 2 * MONTH) == 0                 # once


def test_the_quiet_starts_at_the_latest_reading_or_mark(cfg, add, ann):
    book = add("Tide Line")
    t = time.time()
    loans.check_out(cfg, ann.id, book)
    out_at = loan_for(cfg, ann, book)["mine"]["out_at"]
    statuses.set_status(cfg, ann.id, book, "incomplete", at=out_at + 5 * DAY)
    assert settle(cfg, ann, out_at + MONTH + DAY) == 0
    assert settle(cfg, ann, out_at + 5 * DAY + MONTH) == 1
    assert rows(cfg)[0]["returned_at"] == out_at + 5 * DAY + MONTH and t <= out_at


def test_reading_again_after_a_quiet_month_is_a_new_loan(cfg, add, ann):
    book = add("Tide Line")
    read(cfg, ann, book, 3, at=time.time() - MONTH - DAY)
    read(cfg, ann, book, 4)                                      # not yet worked out, then read
    first, second = rows(cfg)
    assert first["how"] == "abandoned" and second["returned_at"] is None


def test_checked_out_by_button_and_never_read_is_abandoned_after_30_days(cfg, add, ann):
    book = add("Tide Line")
    assert loans.check_out(cfg, ann.id, book)["mine"] is not None
    out_at = rows(cfg)[0]["out_at"]
    assert settle(cfg, ann, out_at + MONTH - 1) == 0
    assert settle(cfg, ann, out_at + MONTH) == 1
    [loan] = rows(cfg)
    assert (loan["how"], loan["returned_at"]) == ("abandoned", out_at + MONTH)


def test_return_early_keeps_the_place_and_status(cfg, add, ann):
    book = add("Tide Line")
    read(cfg, ann, book, 3)
    place, was = reading.get_progress(cfg, ann.id, book), status(cfg, ann, book)
    assert loans.give_back(cfg, ann.id, book) == {"mine": None, "others": []}
    assert reading.get_progress(cfg, ann.id, book) == place and status(cfg, ann, book) == was == "reading"
    [loan] = rows(cfg)
    assert loan["how"] == "returned"
    assert loan_entries(cfg)[0]["text"] == "returned early"
    assert loans.give_back(cfg, ann.id, book) == {"mine": None, "others": []}   # nothing out: nothing logged
    assert len(loan_entries(cfg)) == 2
    with pytest.raises(LookupError):
        loans.give_back(cfg, ann.id, 9999)
    with pytest.raises(LookupError):
        loans.check_out(cfg, ann.id, 9999)


def test_status_by_hand_moves_the_loan(cfg, add, ann):
    book = add("Tide Line")

    def mark(s):
        statuses.set_status(cfg, ann.id, book, s)
        return [(r["how"], r["returned_at"] is None) for r in rows(cfg)]

    assert mark("reading") == [(None, True)]
    assert mark("finished") == [("finished", False)]
    assert mark("incomplete") == [("finished", False), (None, True)]
    assert mark("abandoned") == [("finished", False), ("abandoned", False)]
    mark("reading")
    assert mark("unread")[-1] == ("returned", False)
    mark("reading")
    assert mark("want")[-1] == ("returned", False)
    assert len(rows(cfg)) == 4 and open_loans(cfg) == []


def test_reopening_an_abandoned_book_checks_it_out_again(cfg, add, ann):
    book = add("Tide Line")
    read(cfg, ann, book, 3, at=time.time() - MONTH - DAY)
    assert status(cfg, ann, book) == "abandoned"
    statuses.opened(cfg, ann.id, book)
    first, second = rows(cfg)
    assert first["how"] == "abandoned" and second["returned_at"] is None
    statuses.opened(cfg, ann.id, book)                           # Reading now: nothing more
    assert len(rows(cfg)) == 2


def test_others_see_who_has_it_but_can_still_read(cfg, add, ann, ben):
    book = add("Tide Line")
    loans.check_out(cfg, ann.id, book)
    assert loan_for(cfg, ben, book) == {"mine": None, "others": ["ann"]}
    read(cfg, ben, book, 3)
    assert reading.get_progress(cfg, ben.id, book)["page"] == 3
    assert loan_for(cfg, ben, book)["mine"] is not None and loan_for(cfg, ben, book)["others"] == ["ann"]
    assert loan_for(cfg, ann, book)["others"] == ["ben"]
    assert library.get_book(cfg, book, ben)["loan"] == loan_for(cfg, ben, book)
    [now] = loans.out_now(cfg)
    assert now["book"]["id"] == book and now["people"] == ["ann", "ben"] and now["since"] == rows(cfg)[0]["out_at"]


def test_two_check_outs_at_once_leave_one_open_loan(cfg, add, ann):
    book = add("Tide Line")
    start, errors = threading.Barrier(8), []

    def go(i):
        try:
            start.wait()
            if i % 2:
                loans.check_out(cfg, ann.id, book)
            else:
                read(cfg, ann, book, 3)
        except Exception as e:   # pragma: no cover - shown below
            errors.append(e)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(open_loans(cfg)) == 1 and len(loan_entries(cfg)) == 1
    with session(cfg.db_path) as con, pytest.raises(Exception):
        con.execute("INSERT INTO loans(user_id, book_id, out_at) VALUES (?, ?, 1)", (ann.id, book))


def test_fill_in_once_from_current_reading(cfg, add, ann, ben):
    reading_, incomplete, finished, unread, marked = (add(t) for t in ("A", "B", "C", "D", "E"))
    now = time.time()
    read(cfg, ann, reading_, 3, at=now - DAY)
    read(cfg, ann, incomplete, 3, at=now - 20 * DAY)
    read(cfg, ann, finished, 9, at=now - DAY)
    statuses.set_status(cfg, ben.id, marked, "reading", at=now - 2 * DAY)
    with session(cfg.db_path) as con:                            # as a library from before loans
        con.execute("DELETE FROM loans")
        con.execute("DELETE FROM activity")
    assert loans.fill_in(cfg) == 3
    got = {(r["user_id"], r["book_id"]): r["out_at"] for r in open_loans(cfg)}
    assert got == {(ann.id, reading_): now - DAY, (ann.id, incomplete): now - 20 * DAY, (ben.id, marked): now - 2 * DAY}
    assert unread and loan_entries(cfg) == []
    assert loans.fill_in(cfg) == 0 and len(rows(cfg)) == 3


def test_the_card_and_routes(client):
    books = client.get("/api/books", params={"sort": "title"}).json()["books"]
    one, two = books[0]["id"], books[1]["id"]
    r = client.post(f"/api/books/{one}/loan")
    assert r.status_code == 200 and r.json()["mine"]["out_at"] > 0 and r.json()["others"] == []
    client.post(f"/api/books/{two}/loan")
    assert client.delete(f"/api/books/{two}/loan").json() == {"mine": None, "others": []}
    assert client.post("/api/books/99999/loan").status_code == 404
    assert client.delete("/api/books/99999/loan").status_code == 404
    assert client.get(f"/api/books/{one}").json()["loan"]["mine"] is not None

    card = client.get("/api/me/loans").json()
    assert [b["id"] for b in card["out"]] == [one] and "out_at" in card["out"][0] and "title" in card["out"][0]
    [back] = card["returned"]
    assert back["id"] == two and back["how"] == "returned" and back["returned_at"] >= back["out_at"]

    out_now = client.get("/api/activity").json()["out_now"]
    assert [(o["book"]["id"], o["people"]) for o in out_now] == [(one, ["admin"])]

    client.post("/api/users", json={"username": "sam", "password": "longpassword"})
    client.post("/api/login", json={"username": "sam", "password": "longpassword"})
    assert client.get(f"/api/books/{one}").json()["loan"] == {"mine": None, "others": ["admin"]}
    assert client.get("/api/me/loans").json() == {"out": [], "returned": []}


def test_merging_two_copies_keeps_loans(cfg, add, ann, ben):
    now = time.time() - 3600
    keep, other = add("Tide Line"), add("Tide Line (copy)")
    read(cfg, ann, keep, 2, at=now + 100)                # Ann has both copies out
    read(cfg, ann, other, 2, at=now)
    read(cfg, ben, other, 3, at=now + 50)                # Ben has only the other copy out
    read(cfg, ben, other, 9, at=now + 60)                # ... and finished it once
    read(cfg, ben, other, 1, at=now + 70)                # ... then started again
    library.merge_books(cfg, keep, other)
    assert [r["out_at"] for r in open_loans(cfg, ann, keep)] == [now]   # one loan, from the earlier copy
    assert len(open_loans(cfg, ben, keep)) == 1 and [r["how"] for r in rows(cfg, ben, keep)] == ["finished", None]
    assert rows(cfg, book=other) == []

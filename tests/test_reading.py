import time

import pytest

from loft import auth, library, reading
from loft.db import session
from loft.settings import update_settings


@pytest.fixture
def sam(cfg):
    return auth.create_user(cfg, "sam", "longpassword")


def fid(cfg, book_id):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE book_id = ?", (book_id,)).fetchone()["id"]


def test_save_and_get(cfg, sam, add):
    b = add("It")
    p = reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=211, pages=588, at=100.0)
    assert (p["page"], p["pages"], p["finished"]) == (211, 588, False)
    assert p["position"] == pytest.approx(211 / 587)
    assert reading.get_progress(cfg, sam.id, b) == p
    assert reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=587, pages=588, at=101.0)["finished"]


def test_late_older_save_is_ignored(cfg, sam, add):
    b = add("It")
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=300, pages=588, at=200.0)
    stale = reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=12, pages=588, at=150.0)
    assert stale["page"] == 300
    assert reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=301, pages=588, at=250.0)["page"] == 301


def test_progress_is_per_person(cfg, sam, add):
    b = add("It")
    other = auth.create_user(cfg, "ana", "longpassword")
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=5, pages=10)
    assert reading.get_progress(cfg, other.id, b) is None


NOW = time.time() - 3600   # an hour ago: recent enough to be Reading (statuses.py)


def test_in_progress(cfg, sam, add):
    a, b, c = add("A"), add("B"), add("C")
    reading.save_progress(cfg, sam.id, a, file_id=fid(cfg, a), page=1, pages=10, at=NOW + 10)
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=9, pages=10, at=NOW + 20)  # finished
    reading.save_progress(cfg, sam.id, c, file_id=fid(cfg, c), page=3, pages=10, at=NOW + 30)
    assert [card["title"] for card, _ in reading.in_progress(cfg, sam.id)] == ["C", "A"]


def test_bookmarks(cfg, sam, add):
    b = add("It")
    other = auth.create_user(cfg, "ana", "longpassword")
    second = reading.add_bookmark(cfg, sam.id, b, file_id=fid(cfg, b), page=40, note="Georgie")
    first = reading.add_bookmark(cfg, sam.id, b, file_id=fid(cfg, b), page=12)
    assert [m["page"] for m in reading.list_bookmarks(cfg, sam.id, b)] == [12, 40]
    assert reading.list_bookmarks(cfg, other.id, b) == []
    assert reading.delete_bookmark(cfg, other.id, second["id"]) is False
    assert reading.delete_bookmark(cfg, sam.id, second["id"]) is True
    assert [m["id"] for m in reading.list_bookmarks(cfg, sam.id, b)] == [first["id"]]


def test_deleting_book_removes_progress_and_bookmarks(cfg, sam, add):
    b = add("It")
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=5, pages=10)
    reading.add_bookmark(cfg, sam.id, b, file_id=fid(cfg, b), page=5)
    with session(cfg.db_path) as con:
        con.execute("DELETE FROM books WHERE id = ?", (b,))
        assert con.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0] == 0


def test_home_continues_reading(cfg, sam, add):
    a = add("Older")
    add("Newest")
    assert library.home(cfg, sam)["hero_kind"] == "new"
    reading.save_progress(cfg, sam.id, a, file_id=fid(cfg, a), page=3, pages=10)
    home = library.home(cfg, sam)
    assert (home["hero"]["title"], home["hero_kind"]) == ("Older", "continue")
    assert home["hero_progress"]["page"] == 3
    assert not any(r["kind"] == "continue" for r in home["rows"])  # one book: the hero is enough


def test_continue_row_with_two_books(cfg, sam, add):
    a, b = add("A"), add("B")
    reading.save_progress(cfg, sam.id, a, file_id=fid(cfg, a), page=3, pages=10, at=NOW + 1)
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=4, pages=10, at=NOW + 2)
    rows = library.home(cfg, sam)["rows"]
    assert rows[0]["kind"] == "continue" and rows[0]["title"] == "Continue reading"
    assert [(c["title"], c["progress"]["page"]) for c in rows[0]["books"]] == [("B", 4), ("A", 3)]


def test_home_rows_follow_settings(cfg, sam, add):
    for i in range(3):
        add(f"S{i}", series="Saga", index=i + 1, tags=["Horror"])
    order = [{"kind": "genres", "visible": True}, {"kind": "recent", "visible": False},
             {"kind": "series", "visible": True}, {"kind": "continue", "visible": True},
             {"kind": "shelves", "visible": True}]
    update_settings(cfg, sam.id, {"look": {"home_rows": order}})
    assert [r["kind"] for r in library.home(cfg, sam)["rows"]] == ["tag", "series"]


def test_get_book_has_your_progress(cfg, sam, add):
    b = add("It")
    reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=7, pages=10)
    assert library.get_book(cfg, b, sam)["progress"]["page"] == 7
    assert library.get_book(cfg, b)["progress"] is None


def test_future_timestamps_are_clamped(cfg, sam, add):
    """A device whose clock runs ahead mustn't lock out every other device's saves."""
    import time
    b = add("It")
    far = time.time() + 10 * 365 * 24 * 3600
    stored = reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=10, pages=100, at=far)
    assert stored["updated_at"] <= time.time() + 61
    assert reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=20, pages=100,
                                 at=time.time() + 120)["page"] == 20


def test_non_finite_timestamps_refused(cfg, sam, add):
    b = add("It")
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=1, pages=10, at=bad)


def test_locator_round_trip(cfg, sam, add):
    b = add("Tide Line")
    p = reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=40, pages=300,
                              locator={"chapter": 3, "progress": 0.25})
    assert p["locator"] == {"chapter": 3, "progress": 0.25}
    assert reading.get_progress(cfg, sam.id, b)["locator"] == {"chapter": 3, "progress": 0.25}
    assert reading.in_progress(cfg, sam.id)[0][1]["locator"] == {"chapter": 3, "progress": 0.25}
    mark = reading.add_bookmark(cfg, sam.id, b, file_id=fid(cfg, b), page=41, locator={"chapter": 3, "progress": 1.7})
    assert mark["locator"] == {"chapter": 3, "progress": 1.0}  # clamped
    assert reading.list_bookmarks(cfg, sam.id, b)[0]["locator"] == {"chapter": 3, "progress": 1.0}
    assert reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=1, pages=10)["locator"] is None


@pytest.mark.parametrize("bad", [{"chapter": -1, "progress": 0}, {"chapter": 1, "progress": "x"},
                                 {"chapter": 1.5, "progress": 0}, {"chapter": 1}, {"chapter": 1, "progress": float("nan")},
                                 "chapter 1"])
def test_bad_locators_refused(cfg, sam, add, bad):
    b = add("Tide Line")
    with pytest.raises(ValueError):
        reading.save_progress(cfg, sam.id, b, file_id=fid(cfg, b), page=1, pages=10, locator=bad)

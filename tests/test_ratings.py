"""Ratings: one to five stars per person and book, and the library's average (src/loft/ratings.py)."""
import threading

import pytest

from loft import activity, auth, library, ratings
from loft.db import session


@pytest.fixture
def ann(cfg):
    return auth.create_user(cfg, "ann", "annannann", admin=True)


@pytest.fixture
def ben(cfg):
    return auth.create_user(cfg, "ben", "benbenben")


def count(cfg):
    with session(cfg.db_path) as con:
        return con.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]


def test_rating_and_the_average(cfg, add, ann, ben):
    bid = add("Tide Line")
    ratings.rate(cfg, ann.id, bid, 4)
    assert ratings.rate(cfg, ben.id, bid, 5) == {"mine": 5, "average": 4.5, "count": 2}
    with session(cfg.db_path) as con:
        assert ratings.summary(con, bid, ann.id) == {"mine": 4, "average": 4.5, "count": 2}
        assert ratings.summary(con, add("Unrated"), ann.id) == {"mine": None, "average": None, "count": 0}
    assert library.get_book(cfg, bid, ann)["rating"] == {"mine": 4, "average": 4.5, "count": 2}


def test_the_average_has_one_decimal(cfg, add, ann, ben):
    carl = auth.create_user(cfg, "carl", "carlcarlcarl")
    bid = add("Tide Line")
    for who, stars in ((ann, 4), (ben, 4), (carl, 5)):
        ratings.rate(cfg, who.id, bid, stars)
    assert ratings.rate(cfg, ann.id, bid, 4)["average"] == 4.3


def test_rating_again_replaces_and_none_clears(cfg, add, ann):
    bid = add("Tide Line")
    ratings.rate(cfg, ann.id, bid, 2)
    assert ratings.rate(cfg, ann.id, bid, 3) == {"mine": 3, "average": 3.0, "count": 1}
    assert count(cfg) == 1
    assert ratings.rate(cfg, ann.id, bid, None) == {"mine": None, "average": None, "count": 0}
    assert ratings.rate(cfg, ann.id, bid, None) == {"mine": None, "average": None, "count": 0}   # nothing to clear
    assert count(cfg) == 0


def test_only_whole_stars_from_one_to_five(cfg, add, ann):
    bid = add("Tide Line")
    for bad in (0, 6, 3.5, True, "4"):
        with pytest.raises(ValueError):
            ratings.rate(cfg, ann.id, bid, bad)
    with pytest.raises(LookupError):
        ratings.rate(cfg, ann.id, 9999, 4)
    assert count(cfg) == 0


def test_ratings_go_with_the_book_or_person(cfg, add, ann, ben):
    bid, other = add("Tide Line"), add("Other")
    ratings.rate(cfg, ann.id, bid, 4)
    ratings.rate(cfg, ben.id, other, 4)
    with session(cfg.db_path) as con:
        con.execute("DELETE FROM books WHERE id = ?", (bid,))
    assert count(cfg) == 1
    auth.delete_user(cfg, ben.id)
    assert count(cfg) == 0


def test_highest_rated_sort(cfg, add, ann, ben):
    unrated, half, five = add("A unrated"), add("B four and a half"), add("C five")
    ratings.rate(cfg, ann.id, five, 5)
    ratings.rate(cfg, ann.id, half, 4)
    ratings.rate(cfg, ben.id, half, 5)
    listed = library.list_books(cfg, kind=None, value=None, sort="rating")["books"]
    assert [b["id"] for b in listed] == [five, half, unrated]


def test_more_readers_win_a_tie(cfg, add, ann, ben):
    one, two = add("A one reader"), add("B two readers")
    ratings.rate(cfg, ann.id, one, 4)
    ratings.rate(cfg, ann.id, two, 4)
    ratings.rate(cfg, ben.id, two, 4)
    listed = library.list_books(cfg, kind=None, value=None, sort="rating")["books"]
    assert [b["id"] for b in listed] == [two, one]


def test_rating_is_logged(cfg, add, ann):
    bid = add("Tide Line")
    ratings.rate(cfg, ann.id, bid, 4)
    e = activity.listing(cfg)["entries"][0]
    assert (e["kind"], e["text"], e["details"]) == ("ratings.rated", "rated it ★★★★☆", {"stars": 4})
    assert e["user"]["name"] == "ann" and e["book"]["title"] == "Tide Line"
    ratings.rate(cfg, ann.id, bid, None)
    e = activity.listing(cfg)["entries"][0]
    assert (e["kind"], e["user"]["name"], e["book"]["title"]) == ("ratings.cleared", "ann", "Tide Line")


def test_the_api_rates_and_members_see_only_the_average(client):
    bid = client.get("/api/books", params={"sort": "title"}).json()["books"][0]["id"]
    r = client.put(f"/api/books/{bid}/rating", json={"stars": 2})
    assert r.status_code == 200 and r.json() == {"mine": 2, "average": 2.0, "count": 1}
    for bad in (0, 6, 3.5, "four"):
        assert client.put(f"/api/books/{bid}/rating", json={"stars": bad}).status_code == 422
    assert client.put("/api/books/99999/rating", json={"stars": 3}).status_code == 404

    client.post("/api/users", json={"username": "sam", "password": "longpassword"})
    client.post("/api/login", json={"username": "sam", "password": "longpassword"})
    book = client.get(f"/api/books/{bid}").json()
    assert book["rating"] == {"mine": None, "average": 2.0, "count": 1}
    assert "admin" not in str(book) and "stars" not in str(book)
    assert client.put(f"/api/books/{bid}/rating", json={"stars": 4}).json() == {"mine": 4, "average": 3.0, "count": 2}
    assert client.put(f"/api/books/{bid}/rating", json={"stars": None}).json() == {"mine": None, "average": 2.0,
                                                                                   "count": 1}
    assert client.get("/api/books", params={"sort": "rating"}).json()["books"][0]["id"] == bid


def test_two_ratings_at_once_leave_one_row(cfg, add, ann):
    bid = add("Tide Line")
    start, errors = threading.Barrier(8), []

    def rate(stars):
        try:
            start.wait()
            ratings.rate(cfg, ann.id, bid, stars)
        except Exception as e:   # pragma: no cover - shown below
            errors.append(e)

    threads = [threading.Thread(target=rate, args=(1 + i % 5,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and count(cfg) == 1

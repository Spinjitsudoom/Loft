import json
import os

import pytest

from alcove import editing
from alcove.db import session
from alcove.library import get_book, search
from alcove.scanner import scan

from conftest import jpg, png


def row(cfg, book_id):
    with session(cfg.db_path) as con:
        return dict(con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())


def touch(path):
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


def test_edit_details(cfg, add):
    bid = add("Old Title")
    editing.edit_book(cfg, bid, {"title": "The  Long Way ", "authors": ["Becky Chambers", " Becky Chambers "],
                                 "series": "Wayfarers", "series_index": 1, "tags": ["Space", "Found family"],
                                 "description": "First.\n\n\nSecond   line.", "published": "2014-07"})
    b = get_book(cfg, bid)
    assert b["title"] == "The Long Way" and b["authors"] == ["Becky Chambers"]
    assert b["series"] == "Wayfarers" and b["series_index"] == 1
    assert b["description"] == "First.\n\nSecond line." and b["published"] == "2014-07"
    r = row(cfg, bid)
    assert r["sort_title"] == "Long Way" and r["author_sort"] == "Becky Chambers"
    assert set(json.loads(r["locked"])) == {"title", "authors", "series", "series_index", "tags", "description",
                                            "published"}
    assert [x["id"] for x in search(cfg, "wayfarers")] == [bid]
    assert search(cfg, "old") == []


def test_series_number_goes_with_the_series(cfg, add):
    bid = add("A", series="S", index=2)
    editing.edit_book(cfg, bid, {"series": ""})
    assert get_book(cfg, bid)["series_index"] is None


@pytest.mark.parametrize("patch, field", [
    ({"title": "  "}, "title"),
    ({"title": "x" * 501}, "title"),
    ({"authors": "Me"}, "authors"),
    ({"authors": ["ok", ""]}, "authors"),
    ({"authors": [f"A{i}" for i in range(21)]}, "authors"),
    ({"series_index": "two"}, "series_index"),
    ({"series_index": -1}, "series_index"),
    ({"series_index": float("nan")}, "series_index"),
    ({"published": "last year"}, "published"),
    ({"published": "2021-02-30"}, "published"),
    ({"tags": ["x" * 61]}, "tags"),
    ({"tags": [f"t{i}" for i in range(51)]}, "tags"),
    ({"description": "x" * 20001}, "description"),
    ({"colour": "red"}, "colour"),
])
def test_bad_details_are_refused_by_name(cfg, add, patch, field):
    bid = add("Book")
    with pytest.raises(ValueError, match=field):
        editing.edit_book(cfg, bid, patch)


def test_required_details(cfg):
    with pytest.raises(ValueError, match="title and at least one author"):
        editing.clean_details({"title": "Book", "authors": []}, require=True)
    assert editing.clean_details({"title": "Book", "authors": ["Me"]}, require=True)["title"] == "Book"


def test_no_such_book(cfg):
    with pytest.raises(LookupError):
        editing.edit_book(cfg, 999, {"title": "x"})


def test_cover(cfg, add):
    bid = add("Book")
    editing.set_cover(cfg, bid, jpg((200, 20, 20), (300, 450)))
    assert row(cfg, bid)["has_cover"] == 1 and "cover" in json.loads(row(cfg, bid)["locked"])
    editing.clear_cover(cfg, bid)
    assert row(cfg, bid)["has_cover"] == 0
    with pytest.raises(ValueError, match="picture"):
        editing.set_cover(cfg, bid, b"not an image")


def test_edits_and_cover_survive_a_changed_file(cfg, make_epub):
    root = cfg.books_dirs[0]
    path = make_epub(root / "Tale.epub", title="Tale", author="A", description="Old blurb")
    scan(cfg)
    with session(cfg.db_path) as con:
        bid = con.execute("SELECT id FROM books").fetchone()["id"]
    editing.edit_book(cfg, bid, {"title": "A Better Title"})
    editing.set_cover(cfg, bid, jpg((10, 200, 10), (300, 450)))
    colour = row(cfg, bid)["cover_color"]
    make_epub(path, title="Tale", author="A", description="New blurb", cover=png((0, 0, 255), (300, 450)))
    touch(path)
    assert scan(cfg).updated == 1
    r = row(cfg, bid)
    assert r["title"] == "A Better Title" and r["description"] == "New blurb"
    assert r["cover_color"] == colour


def test_edits_survive_a_calibre_change(cfg, make_calibre_db):
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 7, "title": "It", "authors": ["Stephen King"], "comment": "<p>Derry.</p>"}])
    scan(cfg)
    with session(cfg.db_path) as con:
        bid = con.execute("SELECT id FROM books").fetchone()["id"]
    editing.edit_book(cfg, bid, {"authors": ["S. King"]})
    (root / "metadata.db").unlink()
    make_calibre_db(root, [{"id": 7, "title": "It", "authors": ["Stephen King"], "comment": "<p>Clowns.</p>"}])
    touch(root / "metadata.db")
    scan(cfg)
    b = get_book(cfg, bid)
    assert b["authors"] == ["S. King"] and b["description"] == "Clowns."


def test_edit_routes(client, cfg):
    from test_api import book_id
    bid = book_id(client, "Tale")
    r = client.patch(f"/api/books/{bid}", json={"title": "Tale Retold", "publisher": "Den Press"})
    assert r.status_code == 200 and r.json()["title"] == "Tale Retold" and r.json()["publisher"] == "Den Press"
    r = client.patch(f"/api/books/{bid}", json={"published": "soon"})
    assert r.status_code == 400 and "published" in r.json()["detail"]
    assert client.patch("/api/books/9999", json={"title": "x"}).status_code == 404

    before = client.get(f"/api/books/{bid}").json()["cover_v"]
    r = client.put(f"/api/books/{bid}/cover", content=jpg((1, 2, 3), (300, 450)), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["has_cover"] is True
    assert client.put(f"/api/books/{bid}/cover", content=b"hello").status_code == 400
    assert client.delete(f"/api/books/{bid}/cover").json()["has_cover"] is False
    assert client.get(f"/api/books/{bid}").json()["cover_v"] >= before

    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    assert client.patch(f"/api/books/{bid}", json={"title": "Mine"}).status_code == 403
    assert client.put(f"/api/books/{bid}/cover", content=jpg((1, 2, 3))).status_code == 403
    assert client.delete(f"/api/books/{bid}/cover").status_code == 403

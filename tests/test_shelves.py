import json

import pytest

from loft import auth, library, reading, settings, shelves
from loft.db import session


@pytest.fixture
def people(cfg):
    return auth.create_user(cfg, "Etta", "longpassword", admin=True), auth.create_user(cfg, "Sam", "longpassword")


def test_want_to_read_comes_first(cfg, people):
    etta, _ = people
    shelves.create(cfg, etta.id, "Beach")
    names = [(s["name"], s["kind"]) for s in shelves.list_shelves(cfg, etta.id)]
    assert names == [("Want to read", "want"), ("Beach", "own")]
    assert shelves.list_shelves(cfg, etta.id)[0]["id"] == shelves.list_shelves(cfg, etta.id)[0]["id"]


def test_create_rename_delete(cfg, people, add):
    etta, _ = people
    s = shelves.create(cfg, etta.id, "  Beach  reads ")
    assert s["name"] == "Beach reads" and s["count"] == 0
    bid = add("Tale")
    shelves.add(cfg, etta.id, s["id"], bid)
    shelves.add(cfg, etta.id, s["id"], bid)  # twice is still once
    assert shelves.for_book(cfg, etta.id, bid) == [s["id"]]
    shelves.rename(cfg, etta.id, s["id"], "Holiday")
    assert [x["name"] for x in shelves.list_shelves(cfg, etta.id)] == ["Want to read", "Holiday"]
    assert shelves.list_shelves(cfg, etta.id)[1]["count"] == 1
    shelves.remove(cfg, etta.id, s["id"], bid)
    assert shelves.for_book(cfg, etta.id, bid) == []
    shelves.delete(cfg, etta.id, s["id"])
    assert len(shelves.list_shelves(cfg, etta.id)) == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, 7])
def test_bad_names(cfg, people, name):
    with pytest.raises(ValueError):
        shelves.create(cfg, people[0].id, name)


def test_names_are_unique_per_person(cfg, people):
    etta, sam = people
    shelves.create(cfg, etta.id, "Beach")
    with pytest.raises(ValueError, match="already have a shelf called"):
        shelves.create(cfg, etta.id, "beach")
    with pytest.raises(ValueError, match="already have a shelf called"):
        shelves.create(cfg, etta.id, "want to read")
    shelves.create(cfg, sam.id, "Beach")


def test_want_to_read_stays(cfg, people):
    etta, _ = people
    want = shelves.list_shelves(cfg, etta.id)[0]["id"]
    with pytest.raises(ValueError):
        shelves.rename(cfg, etta.id, want, "Later")
    with pytest.raises(ValueError):
        shelves.delete(cfg, etta.id, want)


def test_other_peoples_shelves_are_out_of_reach(cfg, people, add):
    etta, sam = people
    s = shelves.create(cfg, etta.id, "Private")
    bid = add("Tale")
    for call in (lambda: shelves.add(cfg, sam.id, s["id"], bid), lambda: shelves.remove(cfg, sam.id, s["id"], bid),
                 lambda: shelves.rename(cfg, sam.id, s["id"], "Mine"), lambda: shelves.delete(cfg, sam.id, s["id"])):
        with pytest.raises(LookupError):
            call()
    with pytest.raises(LookupError):
        library.list_books(cfg, kind="shelf", value=str(s["id"]), user=sam)
    with pytest.raises(LookupError):
        shelves.add(cfg, etta.id, s["id"], 9999)


def test_shelf_and_finished_lists(cfg, people, add):
    etta, sam = people
    a, b = add("Alpha"), add("Beta")
    s = shelves.create(cfg, etta.id, "Beach")
    shelves.add(cfg, etta.id, s["id"], b)
    assert [x["title"] for x in library.list_books(cfg, kind="shelf", value=str(s["id"]), user=etta)["books"]] == ["Beta"]
    reading.save_progress(cfg, etta.id, a, file_id=_file(cfg, a), page=9, pages=10)
    assert [x["title"] for x in library.list_books(cfg, kind="finished", value="", user=etta)["books"]] == ["Alpha"]
    assert library.list_books(cfg, kind="finished", value="", user=sam)["total"] == 0
    assert library.get_book(cfg, b, etta)["shelves"] == [s["id"]]
    assert library.get_book(cfg, b, sam)["shelves"] == []


def _file(cfg, book_id):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE book_id = ?", (book_id,)).fetchone()["id"]


def test_home_rows_for_shelves(cfg, people, add):
    etta, _ = people
    a = add("Alpha")
    b = add("Beta")
    want = shelves.list_shelves(cfg, etta.id)[0]["id"]
    shelves.create(cfg, etta.id, "Empty")
    shelves.add(cfg, etta.id, want, b)
    rows = [(r["kind"], r["title"]) for r in library.home(cfg, etta)["rows"]]
    assert ("shelf", "Want to read") in rows and ("shelf", "Empty") not in rows
    reading.save_progress(cfg, etta.id, a, file_id=_file(cfg, a), page=9, pages=10)   # (reading b would take it off Want to read)
    rows = [(r["kind"], r["title"]) for r in library.home(cfg, etta)["rows"]]
    assert rows.index(("shelf", "Want to read")) < rows.index(("finished", "Finished")) < rows.index(("recent", "Recently added"))


def test_old_home_rows_keep_their_order(cfg, people):
    etta, _ = people
    old = [{"kind": "series", "visible": True}, {"kind": "continue", "visible": True},
           {"kind": "recent", "visible": False}, {"kind": "genres", "visible": True}]
    with session(cfg.db_path) as con:
        con.execute("INSERT INTO user_settings(user_id, data) VALUES (?, ?)",
                    (etta.id, json.dumps({"look": {"home_rows": old}})))
    rows = settings.get_settings(cfg, etta.id)["look"]["home_rows"]
    assert rows == old + [{"kind": "shelves", "visible": True}]


def test_shelf_routes(client):
    from test_api import book_id
    bid = book_id(client, "Tale")
    lst = client.get("/api/shelves").json()
    assert lst[0]["name"] == "Want to read"
    s = client.post("/api/shelves", json={"name": "Beach"}).json()
    assert client.post("/api/shelves", json={"name": "beach"}).status_code == 400
    assert client.put(f"/api/shelves/{s['id']}/books/{bid}").status_code == 200
    assert client.get(f"/api/books/{bid}").json()["shelves"] == [s["id"]]
    assert client.get(f"/api/books?kind=shelf&value={s['id']}").json()["total"] == 1
    assert client.patch(f"/api/shelves/{s['id']}", json={"name": "Sun"}).json()["name"] == "Sun"
    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    assert client.get(f"/api/books?kind=shelf&value={s['id']}").status_code == 404
    assert client.put(f"/api/shelves/{s['id']}/books/{bid}").status_code == 404
    assert client.delete(f"/api/shelves/{s['id']}").status_code == 404
    assert [x["name"] for x in client.get("/api/shelves").json()] == ["Want to read"]

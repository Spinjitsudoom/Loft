"""The activity log: what happened in the library, for admins (src/loft/activity.py)."""
import time

from loft import activity
from loft.db import session

DAY = 24 * 3600


def entries(cfg, **kw):
    return activity.listing(cfg, **kw)["entries"]


def test_entries_come_newest_first_and_page(cfg):
    now = time.time()
    with session(cfg.db_path) as con:
        for i in range(60):
            activity.record(con, "loft.scan", f"scan {i}", at=now - 60 + i)
    first = activity.listing(cfg, limit=50)
    assert len(first["entries"]) == 50 and first["more"]
    assert first["entries"][0]["text"] == "scan 59" and first["entries"][0]["group"] == "loft"
    rest = activity.listing(cfg, before=first["entries"][-1]["id"], limit=50)
    assert [e["text"] for e in rest["entries"]] == [f"scan {i}" for i in range(9, -1, -1)] and not rest["more"]


def test_names_outlive_what_they_name(cfg, add):
    from loft import auth
    sam = auth.create_user(cfg, "sam", "longpassword")
    bid = add("Tide Line")
    with session(cfg.db_path) as con:
        activity.record(con, "books.edited", "edited the details", user_id=sam.id, book_id=bid)
    e = entries(cfg)[0]
    assert e["user"] == {"id": sam.id, "name": "sam", "exists": True}
    assert e["book"] == {"id": bid, "title": "Tide Line", "exists": True}
    auth.delete_user(cfg, sam.id)
    with session(cfg.db_path) as con:
        con.execute("DELETE FROM books WHERE id = ?", (bid,))
    e = entries(cfg)[0]
    assert e["user"] == {"id": sam.id, "name": "sam", "exists": False}
    assert e["book"] == {"id": bid, "title": "Tide Line", "exists": False}


def test_loft_itself_and_entries_without_a_book(cfg):
    with session(cfg.db_path) as con:
        activity.record(con, "loft.backup", "made a backup (scheduled)", details={"name": "x.zip"})
    e = entries(cfg)[0]
    assert e["user"] is None and e["book"] is None and e["details"] == {"name": "x.zip"}


def test_filter_by_person_and_group(cfg):
    from loft import auth
    sam, ann = auth.create_user(cfg, "sam", "longpassword"), auth.create_user(cfg, "ann", "longpassword")
    with session(cfg.db_path) as con:
        activity.record(con, "sign_in.ok", "signed in", user_id=sam.id)
        activity.record(con, "sign_in.ok", "signed in", user_id=ann.id)
        activity.record(con, "ratings.rated", "rated it", user_id=sam.id)
    assert [e["kind"] for e in entries(cfg, user_id=sam.id)] == ["ratings.rated", "sign_in.ok"]
    assert [e["user"]["name"] for e in entries(cfg, group="sign_in")] == ["ann", "sam"]
    listing = activity.listing(cfg)
    assert {"id": sam.id, "name": "sam"} in listing["people"] and listing["groups"] == activity.GROUPS


def test_a_year_is_kept(cfg):
    now = time.time()
    with session(cfg.db_path) as con:
        activity.trim(con, now)                       # trimmed today: writing doesn't trim again
        activity.record(con, "loft.scan", "old", at=now - 400 * DAY)
        activity.record(con, "loft.scan", "recent", at=now - 10 * DAY)
        con.execute("UPDATE meta SET value = ? WHERE key = 'activity_trimmed_at'", (str(now - 2 * DAY),))
        assert activity.trim(con, now) == 1
        activity.record(con, "loft.scan", "older still", at=now - 500 * DAY)
        assert activity.trim(con, now) == 0          # once a day
    assert [e["text"] for e in entries(cfg)] == ["older still", "recent"]


def test_a_failed_write_never_stops_the_action(cfg, caplog):
    with session(cfg.db_path) as con:
        pass
    activity.record(con, "loft.scan", "after closing")   # the connection is closed: no exception
    assert "Couldn’t write to the activity log" in caplog.text


def test_only_admins_see_the_log(client):
    assert client.get("/api/activity").status_code == 200
    assert client.post("/api/users", json={"username": "sam", "password": "longpassword"}).status_code in (200, 201)
    client.post("/api/login", json={"username": "sam", "password": "longpassword"})
    assert client.get("/api/activity").status_code == 403

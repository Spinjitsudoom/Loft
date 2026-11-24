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
    assert e["user"] == {"id": None, "name": "sam", "exists": False}      # let go: the id may be used again
    assert e["book"] == {"id": None, "title": "Tide Line", "exists": False}


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
    assert [e["text"] for e in entries(cfg)] == ["recent", "older still"]   # in time order


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


# ---------- what gets logged ----------

def newest(cfg, **kw):
    return entries(cfg, **kw)[0]


def book_id(cfg, title):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM books WHERE title = ?", (title,)).fetchone()[0]


def test_sign_ins_are_logged_and_failures_name_who_was_tried(client, cfg):
    assert client.post("/api/login", json={"username": "admin", "password": "longpassword"}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("sign_in.ok", "signed in", "admin")
    assert client.post("/api/login", json={"username": "mallory", "password": "guessing"}).status_code == 401
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("sign_in.failed", "couldn’t sign in", "mallory")
    assert e["user"]["id"] is None and e["details"]["ip"]
    assert client.post("/api/login", json={"username": "admin", "password": "longpassword"}).status_code == 200


def test_people_changes_are_logged(client, cfg):
    from test_members import member
    client.patch("/api/library", json={"join_requests": True})
    assert client.post("/api/join", json={"username": "ann", "password": "annannann"}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("people.asked", "asked to join", "ann")
    rid = client.get("/api/join-requests").json()[0]["id"]
    assert client.post(f"/api/join-requests/{rid}/approve").status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("people.approved", "approved ann", "admin")
    assert e["details"] == {"person": "ann"}

    member(client, "sam", "samsamsam")
    e = next(x for x in entries(cfg) if x["kind"] == "people.added")
    assert (e["text"], e["user"]["name"]) == ("added sam", "admin")
    sam = next(u for u in client.get("/api/users").json() if u["username"] == "sam")
    assert client.patch(f"/api/users/{sam['id']}", json={"admin": True}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("people.admin", "made sam an admin", "admin")
    client.patch(f"/api/users/{sam['id']}", json={"admin": False})
    assert newest(cfg)["text"] == "made sam a member"
    assert client.delete(f"/api/users/{sam['id']}").status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("people.removed", "removed sam", "admin")


def test_book_edits_name_the_fields(client, cfg):
    from conftest import png
    tale, it = book_id(cfg, "Tale"), book_id(cfg, "It")
    assert client.patch(f"/api/books/{tale}", json={"title": "Tale Retold", "tags": ["sea"]}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]["title"]) == \
        ("books.edited", "edited the details of", "admin", "Tale Retold")
    assert e["details"] == {"fields": ["title", "tags"]}

    assert client.put(f"/api/books/{tale}/cover", content=png((1, 2, 3))).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["book"]["title"]) == ("books.cover", "changed the cover of", "Tale Retold")
    assert client.delete(f"/api/books/{tale}/cover").status_code == 200
    assert (newest(cfg)["kind"], newest(cfg)["text"]) == ("books.cover", "removed the cover of")

    assert client.post(f"/api/books/{it}/merge", json={"other": tale}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["book"]["title"]) == ("books.edited", "merged another copy into", "It")
    assert e["details"] == {"other": "Tale Retold"}


def test_uploads_and_suggestions_are_logged(client, cfg, tmp_path, make_epub):
    from test_members import member
    from test_submissions import DETAILS, epub
    token = client.put("/api/uploads?name=Mine.epub", content=epub(tmp_path, make_epub, "Mine")).json()["token"]
    bid = client.post(f"/api/uploads/{token}/save", json={"details": {**DETAILS, "title": "Mine"}}).json()["book_id"]
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]) == \
        ("books.added", "uploaded", "admin", {"id": bid, "title": "Mine", "exists": True})

    sam = member(client)
    token = sam.put("/api/uploads?name=Fresh.epub", content=epub(tmp_path, make_epub, "Fresh")).json()["token"]
    assert sam.post(f"/api/uploads/{token}/submit", json={"details": {**DETAILS, "title": "Fresh"}}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("requests.submitted", "suggested a book", "sam")
    assert e["details"] == {"title": "Fresh"}
    sid = client.get("/api/submissions").json()[0]["id"]
    bid = client.post(f"/api/submissions/{sid}/approve", json={"details": {**DETAILS, "title": "Fresh"}}).json()["book_id"]
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]["id"], e["book"]["title"]) == \
        ("books.added", "added", "admin", bid, "Fresh")


def test_requests_and_comments_are_logged(client, cfg):
    from test_members import member
    sam = member(client)
    rid = sam.post("/api/requests", json={"title": "Gyo", "author": "Junji Ito"}).json()["id"]
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("requests.asked", "asked for Gyo", "sam")
    tale = book_id(cfg, "Tale")
    assert client.post(f"/api/requests/{rid}/fulfil", json={"book_id": tale}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]["title"]) == \
        ("requests.fulfilled", "fulfilled the request for Gyo", "admin", "Tale")

    assert sam.post(f"/api/books/{tale}/discussion", json={"body": "A secret twist"}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]["title"]) == \
        ("discussion.comment", "commented on", "sam", "Tale")
    assert "secret" not in str(e)


def test_settings_backups_and_updates_are_logged(client, cfg, tmp_path, monkeypatch):
    import json
    from loft import backups, updates
    assert client.patch("/api/library", json={"name": "Home", "google_books_key": ""}).status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("loft.settings", "changed library settings", "admin")
    assert e["details"] == {"fields": ["google_books_key", "name"]}

    name = client.post("/api/backups").json()["name"]
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["details"]) == \
        ("loft.backup", "made a backup", "admin", {"name": name})
    monkeypatch.setattr(backups, "due", lambda *a: True)
    made = backups.step(cfg, time.time() + 2)
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"], e["details"]) == \
        ("loft.backup", "made a backup (scheduled)", None, {"name": made.name})

    # A newer Loft is downloaded, then installed.
    home = tmp_path / "opt" / "loft-server"
    home.mkdir(parents=True)
    (home / "loft-server").write_text("old")
    monkeypatch.setenv("LOFT_UPDATES_INSTALL", str(home))
    monkeypatch.setattr(updates, "current_version", lambda: "0.1.1")
    monkeypatch.setattr(updates, "system", lambda: ("linux", "x64"))
    monkeypatch.setattr(updates.sys, "platform", "linux")
    monkeypatch.setattr(updates, "_get", lambda url, limit: json.dumps(
        {"tag_name": "v0.1.2", "draft": False, "prerelease": False, "assets": []}).encode())
    monkeypatch.setattr(updates, "_fetch_notes", lambda assets, version: [])

    def fetch(version, assets):
        updates.staging_dir(version).mkdir()
        (updates.staging_dir(version) / updates.PROGRAM).write_text("new")
    monkeypatch.setattr(updates, "_fetch", fetch)
    assert updates.check(cfg)["ready"]
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]) == ("loft.update_ready", "downloaded Loft 0.1.2", None)

    class Now:
        def __init__(self, delay, call, args):
            self.call, self.args = call, args

        def start(self):
            self.call(*self.args)
    monkeypatch.setattr(updates.threading, "Timer", Now)
    monkeypatch.setattr(updates.os, "execve", lambda *a: None)
    monkeypatch.setattr(updates, "_flush_logs", lambda: None)
    assert client.post("/api/updates/install").status_code == 202
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"]) == ("loft.update_installed", "restarted into Loft 0.1.2", "admin")

    r = client.post(f"/api/backups/{made.name}/restore")
    assert r.status_code == 200, r.text
    e = newest(cfg)   # written into the library as restored
    assert (e["kind"], e["text"], e["user"]["name"]) == ("loft.restore", "restored a backup", "admin")
    assert e["user"]["exists"] and e["details"] == {"name": made.name, "before": r.json()["before"]}


def test_filling_in_and_undoing_are_logged(client, cfg, monkeypatch):
    from loft import autofill, lookups
    tale = book_id(cfg, "Tale")
    with session(cfg.db_path) as con:
        con.execute("INSERT OR REPLACE INTO autofill(book_id, state, tries) VALUES (?, 'waiting', 0)", (tale,))
    monkeypatch.setattr(lookups, "search", lambda cfg, **kw: [
        {"title": "Tale", "authors": ["A"], "description": "Once upon a time.", "tags": ["fable"], "source": "test"}])
    assert autofill.fill_book(cfg, tale) == "filled"
    e = newest(cfg)
    assert (e["kind"], e["user"], e["book"]["title"]) == ("books.filled", None, "Tale")
    assert e["text"] == "filled in the details of" and e["details"]["fields"] == ["tags", "description"]
    assert e["details"] == {"fields": ["tags", "description"]}
    assert client.post(f"/api/autofill/{tale}/undo").status_code == 200
    e = newest(cfg)
    assert (e["kind"], e["text"], e["user"]["name"], e["book"]["title"]) == \
        ("books.unfilled", "undid the automatic details of", "admin", "Tale")


def test_a_big_scan_logs_50_books_then_a_summary(cfg, make_pdf):
    from loft.scanner import scan
    for i in range(60):
        make_pdf(cfg.books_dirs[0] / f"Book {i:02}.pdf", title=f"Book {i:02}")
    scan(cfg)
    log = activity.listing(cfg, limit=200)["entries"]
    assert log[0]["kind"] == "loft.scan" and log[0]["user"] is None and log[0]["text"] == "scanned the library"
    assert log[0]["details"] == {"added": 60, "updated": 0, "removed": 0}
    added = [e for e in log if e["kind"] == "books.added"]
    assert len([e for e in added if e["book"]]) == 50 and all(e["text"] == "added" for e in added if e["book"])
    assert [e["text"] for e in added if not e["book"]] == ["added 10 more books"]
    assert len(log) == 52

    for i in range(55):
        (cfg.books_dirs[0] / f"Book {i:02}.pdf").unlink()
    scan(cfg)
    log = activity.listing(cfg, limit=200)["entries"]
    assert log[0]["kind"] == "loft.scan" and log[0]["details"] == {"added": 0, "updated": 0, "removed": 55}
    removed = [e for e in log if e["kind"] == "books.removed"]
    assert len([e for e in removed if e["book"]]) == 50
    assert [e["text"] for e in removed if not e["book"]] == ["removed 5 more books"]
    gone = next(e for e in removed if e["book"])
    assert (gone["text"], gone["details"]["after"]) == ("removed", "(gone from the books folder)") and gone["book"]["title"].startswith("Book ")
    assert not gone["book"]["exists"]


def test_a_scan_that_changed_nothing_logs_nothing(client, cfg):
    from loft.scanner import scan
    before = activity.listing(cfg, limit=500)["entries"]
    assert before   # the first scan was logged
    scan(cfg)
    assert activity.listing(cfg, limit=500)["entries"] == before


def test_reading_is_never_logged(client, cfg):
    bid = book_id(cfg, "Three Pages")
    with session(cfg.db_path) as con:
        fid = con.execute("SELECT id FROM book_files WHERE book_id = ?", (bid,)).fetchone()[0]
    before = {e["id"] for e in activity.listing(cfg, limit=500)["entries"]}
    for page in (1, 2, 3):
        r = client.put(f"/api/books/{bid}/progress", json={"file_id": fid, "page": page, "pages": 3})
        assert r.status_code == 200, r.text
    new = [e for e in activity.listing(cfg, limit=500)["entries"] if e["id"] not in before]
    assert all(e["group"] == "loans" for e in new)


def test_setting_up_the_first_admin_is_logged(app_lib):
    assert app_lib.post("/api/setup", json={"username": "admin", "password": "longpassword"}).status_code == 200
    e = app_lib.get("/api/activity?group=people").json()["entries"]
    assert [(x["kind"], x["user"]["name"], x["text"]) for x in e] == [("people.added", "admin", "set up Loft")]


def test_entries_are_in_time_order_even_when_written_later(cfg):
    now = time.time()
    with session(cfg.db_path) as con:
        activity.record(con, "sign_in.ok", "signed in", at=now)
        activity.record(con, "loans.returned", "returned", at=now - 10 * DAY)    # a return worked out later
        activity.record(con, "sign_in.ok", "signed in again", at=now - 5)
    assert [e["text"] for e in entries(cfg)] == ["signed in", "signed in again", "returned"]
    first = activity.listing(cfg, limit=2)
    assert [e["text"] for e in activity.listing(cfg, before=first["entries"][-1]["id"])["entries"]] == ["returned"]


def test_a_new_person_never_inherits_a_removed_ones_entries(cfg, add):
    from loft import auth
    gone = auth.create_user(cfg, "test", "longpassword")
    book = add("Old Book")
    with session(cfg.db_path) as con:
        activity.record(con, "sign_in.ok", "signed in", user_id=gone.id, book_id=book)
    auth.delete_user(cfg, gone.id)
    with session(cfg.db_path) as con:
        con.execute("DELETE FROM books WHERE id = ?", (book,))
    new = auth.create_user(cfg, "cassidy", "longpassword")
    fresh = add("New Book")
    assert entries(cfg, user_id=new.id) == []
    e = entries(cfg)[0]
    assert e["user"]["name"] == "test" and not e["user"]["exists"] and e["user"]["id"] != new.id
    assert e["book"]["title"] == "Old Book" and not e["book"]["exists"] and e["book"]["id"] != fresh


def test_writing_never_raises_even_when_the_database_cant_be_opened(cfg, caplog, tmp_path):
    (tmp_path / "not-a-folder").write_text("a file where Loft's data folder should be")
    cfg.data_dir = tmp_path / "not-a-folder"
    activity.note(cfg, "loft.scan", "scanned")
    with activity.writing(cfg) as con:
        con.execute("SELECT 1")                           # con is None: the error stays in here
    assert "activity log" in caplog.text


def test_a_failed_sign_in_with_no_name_isnt_shown_as_loft(client):
    client.post("/api/login", json={"username": "", "password": "wrongwrongwrong"})
    client.post("/api/login", json={"username": "admin", "password": "longpassword"})
    e = client.get("/api/activity?group=sign_in").json()["entries"]
    failed = [x for x in e if x["kind"] == "sign_in.failed"][0]
    assert failed["user"]["name"] == "(no name)"


def test_taking_a_folder_out_logs_its_books(cfg, tmp_path, make_pdf):
    from loft import libsettings
    from loft.scanner import scan
    extra = tmp_path / "extra"
    make_pdf(extra / "One.pdf", title="One")
    make_pdf(extra / "Two.pdf", title="Two")
    libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0]), str(extra)]})
    scan(cfg)
    libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0])]})
    gone = [e for e in entries(cfg, group="books") if e["text"] == "removed"]
    assert sorted(e["book"]["title"] for e in gone) == ["One", "Two"]
    assert all(e["details"]["after"] == "(its folder was taken out of the library)" for e in gone)

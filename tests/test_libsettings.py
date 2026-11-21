import os

import pytest

from loft import libsettings, updates
from loft.db import session
from loft.scanner import last_report, scan


def titles(cfg):
    with session(cfg.db_path) as con:
        return sorted(r["title"] for r in con.execute("SELECT title FROM books"))


def test_defaults_come_from_config(cfg):
    lib = libsettings.get_library(cfg)
    assert lib == {"name": "", "books_dirs": [str(cfg.books_dirs[0])], "upload_dir": str(cfg.books_dirs[0]),
                   "scan_interval_minutes": cfg.scan_interval_minutes, "allow_txt": False, "online_lookups": True, "auto_lookup": True,
                   "google_books": False, "hardcover": False, "isbndb": False, "join_requests": False, "check_updates": True, "sections": [], "sections_suggested": True}


def test_name_round_trips_and_is_tidied(cfg):
    assert libsettings.update_library(cfg, {"name": "  The   Den "})["name"] == "The Den"
    assert libsettings.get_library(cfg)["name"] == "The Den"


@pytest.mark.parametrize("patch, field", [
    ({"colour": "red"}, "colour"),
    ({"name": "x" * 41}, "name"),
    ({"name": 3}, "name"),
    ({"books_dirs": []}, "books_dirs"),
    ({"books_dirs": ["relative/path"]}, "books_dirs"),
    ({"books_dirs": ["/no/such/folder/anywhere"]}, "books_dirs"),
    ({"books_dirs": "/tmp"}, "books_dirs"),
    ({"upload_dir": "/tmp"}, "upload_dir"),
    ({"scan_interval_minutes": 4}, "scan_interval_minutes"),
    ({"scan_interval_minutes": 1441}, "scan_interval_minutes"),
    ({"scan_interval_minutes": True}, "scan_interval_minutes"),
    ({"allow_txt": "yes"}, "allow_txt"),
    ({"online_lookups": 1}, "online_lookups"),
])
def test_bad_values_are_refused_by_name(cfg, patch, field):
    with pytest.raises(ValueError, match=field):
        libsettings.update_library(cfg, patch)


def test_duplicate_folders_are_dropped(cfg, tmp_path):
    other = tmp_path / "more"
    other.mkdir()
    root = str(cfg.books_dirs[0])
    lib = libsettings.update_library(cfg, {"books_dirs": [root, str(other), root]})
    assert lib["books_dirs"] == [root, str(other)]
    assert libsettings.books_dirs(cfg) == [cfg.books_dirs[0], other]


def test_plain_text_switch(cfg, make_pdf):
    root = cfg.books_dirs[0]
    make_pdf(root / "Book.pdf", title="Book")
    (root / "Notes.txt").write_text("Chapter 1\n\nHello\n")
    scan(cfg)
    assert titles(cfg) == ["Book"]
    libsettings.update_library(cfg, {"allow_txt": True})
    scan(cfg)
    assert titles(cfg) == ["Book", "Notes"]
    libsettings.update_library(cfg, {"allow_txt": False})
    scan(cfg)
    assert titles(cfg) == ["Book"]


def test_removing_a_folder_removes_its_books_at_once(cfg, tmp_path, make_pdf):
    other = tmp_path / "more"
    make_pdf(cfg.books_dirs[0] / "Kept.pdf", title="Kept")
    make_pdf(other / "Gone.pdf", title="Gone")
    libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0]), str(other)], "upload_dir": str(other)})
    scan(cfg)
    assert titles(cfg) == ["Gone", "Kept"]
    lib = libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0])]})
    assert titles(cfg) == ["Kept"]
    assert lib["upload_dir"] == str(cfg.books_dirs[0])


def test_folder_missing_from_config_alone_removes_nothing(cfg, tmp_path, make_pdf):
    make_pdf(cfg.books_dirs[0] / "Kept.pdf", title="Kept")
    scan(cfg)
    cfg.books_dirs = [tmp_path / "typo"]
    assert scan(cfg).removed == 0
    assert titles(cfg) == ["Kept"]


def test_scan_report(cfg, make_pdf, make_calibre_db):
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 1, "title": "Here", "authors": ["A"]}, {"id": 2, "title": "Lost", "authors": ["B"]}])
    lost = [p for p in root.rglob("*.pdf") if "Lost" in str(p)]
    for p in lost:
        p.unlink()
    make_pdf(root / "Sub" / "A.pdf")
    (root / "Sub").chmod(0)
    try:
        scan(cfg)
    finally:
        (root / "Sub").chmod(0o755)
    report = last_report(cfg)
    assert report["added"] == 1 and report["at"] > 0
    if os.geteuid() != 0:
        assert report["unreadable"] == [str(root / "Sub")]
    assert report["calibre_missing"] == [str(p) for p in lost]
    assert report["unreachable"] == []


def test_scan_report_names_unreachable_folders(cfg, tmp_path):
    cfg.books_dirs = [tmp_path / "gone"]
    scan(cfg)
    assert last_report(cfg)["unreachable"] == [str(tmp_path / "gone")]


def test_status_shows_the_name_before_sign_in(app_lib, cfg):
    libsettings.update_library(cfg, {"name": "The Den"})
    assert app_lib.get("/api/status").json() == {"setup_needed": True, "name": "The Den", "join_requests": False,
                                                  "version": updates.current_version()}


def test_library_routes(client, app_lib):
    assert client.get("/api/library").json()["allow_txt"] is False
    r = client.patch("/api/library", json={"name": "Den"})
    assert r.status_code == 200 and r.json()["name"] == "Den"
    r = client.patch("/api/library", json={"scan_interval_minutes": 1})
    assert r.status_code == 400 and "scan_interval_minutes" in r.json()["detail"]
    assert "report" in client.get("/api/scan").json()
    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    assert client.get("/api/library").status_code == 403
    assert client.patch("/api/library", json={"name": "x"}).status_code == 403


@pytest.mark.parametrize("inner", [True, False])
def test_folders_inside_each_other_are_refused(cfg, inner):
    root = cfg.books_dirs[0]
    sub = root / "Comics"
    sub.mkdir()
    dirs = [str(root), str(sub)] if inner else [str(sub), str(root)]
    with pytest.raises(ValueError, match="inside"):
        libsettings.update_library(cfg, {"books_dirs": dirs})


def test_same_folder_by_another_path_is_refused(cfg, tmp_path):
    link = tmp_path / "alias"
    link.symlink_to(cfg.books_dirs[0])
    with pytest.raises(ValueError, match="inside|same"):
        libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0]), str(link)]})


def test_nested_folders_from_config_dont_churn(cfg, make_pdf):
    from loft import reading, auth
    root = cfg.books_dirs[0]
    make_pdf(root / "Comics" / "A.pdf", title="A", pages=3)
    cfg.books_dirs = [root, root / "Comics"]
    scan(cfg)
    with session(cfg.db_path) as con:
        bid = con.execute("SELECT id FROM books").fetchone()["id"]
        fid = con.execute("SELECT id FROM book_files").fetchone()["id"]
    sam = auth.create_user(cfg, "Sam", "longpassword")
    reading.save_progress(cfg, sam.id, bid, file_id=fid, page=1, pages=3)
    for _ in range(2):
        result = scan(cfg)
        assert (result.added, result.removed) == (0, 0)
    assert reading.get_progress(cfg, sam.id, bid)["page"] == 1


def test_removing_a_folder_during_a_scan_keeps_it_removed(cfg, tmp_path, make_pdf, monkeypatch):
    import threading
    import time as _time
    from loft import scanner
    a, b = cfg.books_dirs[0], tmp_path / "b"
    make_pdf(a / "InA.pdf", title="InA")
    make_pdf(b / "InB.pdf", title="InB")
    libsettings.update_library(cfg, {"books_dirs": [str(a), str(b)]})
    scan(cfg)
    assert titles(cfg) == ["InA", "InB"]
    real = scanner._scan_root
    worker = []

    def slow(cfg_, con, root, txt=False):
        if root == a and not worker:
            t = threading.Thread(target=libsettings.update_library, args=(cfg, {"books_dirs": [str(a)]}))
            worker.append(t)
            t.start()
            _time.sleep(0.3)  # the removal is saved and waiting while this folder is scanned
        return real(cfg_, con, root, txt)

    monkeypatch.setattr(scanner, "_scan_root", slow)
    scan(cfg)
    worker[0].join()
    scan(cfg)
    assert titles(cfg) == ["InA"]

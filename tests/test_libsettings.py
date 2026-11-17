import os

import pytest

from alcove import libsettings
from alcove.db import session
from alcove.scanner import last_report, scan


def titles(cfg):
    with session(cfg.db_path) as con:
        return sorted(r["title"] for r in con.execute("SELECT title FROM books"))


def test_defaults_come_from_config(cfg):
    lib = libsettings.get_library(cfg)
    assert lib == {"name": "", "books_dirs": [str(cfg.books_dirs[0])], "upload_dir": str(cfg.books_dirs[0]),
                   "scan_interval_minutes": cfg.scan_interval_minutes, "allow_txt": False, "online_lookups": True}


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
    assert app_lib.get("/api/status").json() == {"setup_needed": True, "name": "The Den"}


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

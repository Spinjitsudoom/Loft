import json
import os
import time

import pytest

from alcove import libsettings, uploads
from alcove.db import session
from alcove.library import get_book
from alcove.scanner import ScanResult, scan

from conftest import jpg


def epub_bytes(tmp_path, make_epub, **kw):
    path = make_epub(tmp_path / "src" / "Tale.epub", title=kw.pop("title", "Tale"), author=kw.pop("author", "A"),
                     cover=jpg((200, 10, 10), (300, 450)), description="A tale.", **kw)
    return path.read_bytes()


def chunks(data, size=1000):
    return (data[i:i + size] for i in range(0, len(data), size))


DETAILS = {"title": "Tale", "authors": ["A"], "series": "", "series_index": None, "description": "A tale.",
           "publisher": "", "published": "", "language": "en", "tags": []}


def test_upload_review_and_save(cfg, tmp_path, make_epub):
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    assert draft["format"] == "epub" and draft["has_cover"] and draft["same_as"] == []
    assert draft["details"]["title"] == "Tale" and draft["details"]["authors"] == ["A"]
    assert draft["details"]["description"] == "A tale."
    assert uploads.draft_cover(cfg, draft["token"]).is_file()

    bid = uploads.save(cfg, draft["token"], {**DETAILS, "tags": ["Fable"]})
    saved = cfg.books_dirs[0] / "A" / "Tale" / "Tale.epub"
    assert saved.is_file()
    b = get_book(cfg, bid)
    assert b["title"] == "Tale" and b["tags"] == ["Fable"] and b["has_cover"]
    with session(cfg.db_path) as con:
        locked = set(json.loads(con.execute("SELECT locked FROM books WHERE id = ?", (bid,)).fetchone()["locked"]))
    assert {"title", "authors", "tags"} <= locked
    assert not (cfg.data_dir / "uploads" / draft["token"]).exists()
    assert scan(cfg) == ScanResult(0, 0, 0)


def test_same_book_is_pointed_out(cfg, tmp_path, make_epub):
    first = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    bid = uploads.save(cfg, first["token"], DETAILS)
    again = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    assert [b["id"] for b in again["same_as"]] == [bid]
    uploads.save(cfg, again["token"], DETAILS)
    assert (cfg.books_dirs[0] / "A" / "Tale" / "Tale (2).epub").is_file()
    assert (cfg.books_dirs[0] / "A" / "Tale" / "Tale.epub").is_file()


def test_not_a_book(cfg):
    with pytest.raises(ValueError, match=r"\.docx"):
        uploads.start(cfg, "Passwords.docx", [b"secret"])
    with pytest.raises(ValueError, match=r"\.txt"):
        uploads.start(cfg, "notes.txt", [b"hello"])
    with pytest.raises(ValueError, match="empty"):
        uploads.start(cfg, "Empty.pdf", [])
    assert not any((cfg.data_dir / "uploads").glob("*/*")) if (cfg.data_dir / "uploads").exists() else True


def test_too_big(cfg, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_UPLOAD", 10)
    with pytest.raises(ValueError, match="too big"):
        uploads.start(cfg, "Big.pdf", [b"x" * 6, b"x" * 6])
    assert list((cfg.data_dir / "uploads").iterdir()) == []


def test_details_are_required(cfg, tmp_path, make_epub):
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    with pytest.raises(ValueError, match="at least one author"):
        uploads.save(cfg, draft["token"], {**DETAILS, "authors": []})
    assert uploads.draft_cover(cfg, draft["token"]) is not None  # the draft waits


@pytest.mark.parametrize("text, want", [
    ("../../x", "x"), ("..", "fallback"), ("CON", "CON_"), ("con.txt", "con_.txt"), ("lpt9", "lpt9_"),
    ("a:b?", "ab"), ('a/b\\c*"<>|', "abc"), ("x" * 300, "x" * 80), ("", "fallback"), ("  .hidden. ", "hidden"),
    ("Tab\tand\nline", "Tab and line"), ("Ébène", "Ébène"),
])
def test_safe_name(text, want):
    assert uploads.safe_name(text, "fallback") == want


def test_hostile_details_stay_inside_the_folder(cfg, tmp_path, make_epub):
    draft = uploads.start(cfg, "../../../evil.epub", chunks(epub_bytes(tmp_path, make_epub)))
    uploads.save(cfg, draft["token"], {**DETAILS, "title": "../..", "authors": [".."]})
    root = cfg.books_dirs[0].resolve()
    saved = [p for p in root.rglob("*.epub")]
    assert len(saved) == 1 and saved[0].is_relative_to(root)
    assert saved[0].relative_to(root).parts == ("Unknown author", "Untitled", "evil.epub")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_folder_that_cannot_be_written(cfg, tmp_path, make_epub):
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    root = cfg.books_dirs[0]
    root.chmod(0o500)
    try:
        with pytest.raises(ValueError, match=f"can’t save into {root}"):
            uploads.save(cfg, draft["token"], DETAILS)
    finally:
        root.chmod(0o755)
    assert not any(root.rglob("*.epub"))
    uploads.save(cfg, draft["token"], DETAILS)
    assert (root / "A" / "Tale" / "Tale.epub").is_file()


def test_uploads_go_to_the_chosen_folder(cfg, tmp_path, make_epub):
    other = tmp_path / "other"
    other.mkdir()
    libsettings.update_library(cfg, {"books_dirs": [str(cfg.books_dirs[0]), str(other)], "upload_dir": str(other)})
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    uploads.save(cfg, draft["token"], DETAILS)
    assert (other / "A" / "Tale" / "Tale.epub").is_file()


def test_bad_tokens(cfg):
    for token in ("../../etc", "short", "x" * 22 + "/"):
        with pytest.raises(LookupError):
            uploads.save(cfg, token, DETAILS)
        with pytest.raises(LookupError):
            uploads.draft_cover(cfg, token)
    with pytest.raises(LookupError):
        uploads.save(cfg, "A" * 22, DETAILS)


def test_old_drafts_are_pruned(cfg, tmp_path, make_epub):
    old = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    new = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    folder = cfg.data_dir / "uploads" / old["token"]
    stale = time.time() - 3 * 86400
    os.utime(folder, (stale, stale))
    uploads.prune_drafts(cfg)
    assert not folder.exists() and (cfg.data_dir / "uploads" / new["token"]).exists()


def test_upload_routes(client, cfg, tmp_path, make_epub):
    data = epub_bytes(tmp_path, make_epub, title="Fresh", author="New Writer")
    r = client.put("/api/uploads?name=Fresh.epub", content=data)
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["details"]["title"] == "Fresh"
    assert client.get(f"/api/uploads/{draft['token']}/cover").headers["content-type"] == "image/jpeg"
    assert client.put("/api/uploads?name=a.docx", content=b"x").status_code == 400
    r = client.post(f"/api/uploads/{draft['token']}/save", json={"details": {**DETAILS, "authors": []}})
    assert r.status_code == 400
    r = client.post(f"/api/uploads/{draft['token']}/save", json={"details": {**DETAILS, "title": "Fresh",
                                                                            "authors": ["New Writer"]},
                                                                "right_to_left": False})
    assert r.status_code == 200
    assert client.get(f"/api/books/{r.json()['book_id']}").json()["title"] == "Fresh"
    assert client.post(f"/api/uploads/{draft['token']}/save", json={"details": DETAILS}).status_code == 404
    other = client.put("/api/uploads?name=Fresh.epub", content=data).json()
    assert client.delete(f"/api/uploads/{other['token']}").status_code == 200
    assert client.get(f"/api/uploads/{other['token']}/cover").status_code == 404

    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    # Members can upload (to send for approval) but can't put a book in the library themselves.
    mine = client.put("/api/uploads?name=Fresh.epub", content=data)
    assert mine.status_code == 200
    assert client.post(f"/api/uploads/{mine.json()['token']}/save", json={"details": DETAILS}).status_code == 403


def test_saving_waits_for_a_running_scan(cfg, tmp_path, make_epub):
    import threading
    from alcove import scanner
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    done = []
    with scanner._scan_lock:
        t = threading.Thread(target=lambda: done.append(uploads.save(cfg, draft["token"], DETAILS)))
        t.start()
        t.join(0.4)
        assert t.is_alive() and not any(cfg.books_dirs[0].rglob("*.epub"))
    t.join(5)
    assert done and (cfg.books_dirs[0] / "A" / "Tale" / "Tale.epub").is_file()


def test_files_without_a_title_are_named_from_the_uploaded_name(cfg, make_pdf, tmp_path):
    data = make_pdf(tmp_path / "x.pdf").read_bytes()
    draft = uploads.start(cfg, "The Name of the Wind.pdf", [data])
    assert draft["details"]["title"] == "The Name of the Wind"


def test_a_cover_that_wont_download_falls_back_to_the_files_own(cfg, tmp_path, make_epub, monkeypatch):
    from alcove import openlibrary
    def down(url, limit):
        raise OSError("no route")
    monkeypatch.setattr(openlibrary, "_get", down)
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    bid = uploads.save(cfg, draft["token"], DETAILS, cover_url="https://covers.openlibrary.org/b/id/1-L.jpg")
    assert get_book(cfg, bid)["has_cover"]


def test_a_manga_can_be_marked_right_to_left_when_added(cfg, tmp_path):
    import zipfile
    from alcove import pages
    from conftest import png
    comic = tmp_path / "Manga.cbz"
    with zipfile.ZipFile(comic, "w") as z:
        z.writestr("01.png", png((90, 90, 90), (80, 120)))
    draft = uploads.start(cfg, "Manga.cbz", [comic.read_bytes()])
    assert draft["has_pages"] is True
    bid = uploads.save(cfg, draft["token"], DETAILS, right_to_left=True)
    fid = get_book(cfg, bid)["files"][0]["id"]
    assert pages.manifest(cfg, fid)["rtl"] is True


def test_books_without_pages_have_no_direction(cfg, tmp_path, make_epub):
    draft = uploads.start(cfg, "Tale.epub", chunks(epub_bytes(tmp_path, make_epub)))
    assert draft["has_pages"] is False

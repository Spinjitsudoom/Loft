import pytest

from alcove import check, editing, library, reading, shelves, auth
from alcove.db import session
from alcove.scanner import scan

from conftest import jpg


def items(cfg, kind=None):
    found = check.problems(cfg)["items"]
    return [i for i in found if kind is None or i["kind"] == kind]


def book_ids(cfg):
    with session(cfg.db_path) as con:
        return {r["title"]: r["id"] for r in con.execute("SELECT id, title FROM books")}


@pytest.fixture
def shelf_lib(cfg, make_pdf, make_epub):
    root = cfg.books_dirs[0]
    make_pdf(root / "Locked.pdf", title="Locked", author="A", encrypt=True)
    good = make_pdf(root / "Good.pdf", title="Good", author="A")
    (root / "Broken.pdf").write_bytes(good.read_bytes()[:200])
    make_pdf(root / "scan_0042.pdf")
    make_epub(root / "Fine.epub", title="Fine", author="B", cover=jpg((1, 2, 3), (300, 450)))
    scan(cfg)
    check.check_files(cfg)
    return root


def test_damaged_and_protected_files(cfg, shelf_lib):
    assert [i["book"]["title"] for i in items(cfg, "protected")] == ["Locked"]
    assert [i["format"] for i in items(cfg, "damaged")] == ["pdf"]
    assert "Fine" not in {i["book"]["title"] for i in items(cfg, "damaged") + items(cfg, "protected")}


def test_files_are_only_checked_again_when_they_change(cfg, shelf_lib, monkeypatch):
    calls = []
    monkeypatch.setattr(check.pages, "manifest", lambda c, fid: calls.append(fid))
    check.check_files(cfg)
    assert calls == []


def test_missing_cover_and_author_and_filename_titles(cfg, shelf_lib):
    ids = book_ids(cfg)
    assert ids["Fine"] not in {i["book"]["id"] for i in items(cfg, "no_cover")}
    no_author = {i["book"]["title"] for i in items(cfg, "no_author")}
    assert "scan 0042" in no_author and not {"Good", "Fine"} & no_author
    from_name = {i["book"]["title"] for i in items(cfg, "filename_title")}
    assert "scan 0042" in from_name and not {"Good", "Fine"} & from_name  # "Good" is the PDF's own title
    editing.edit_book(cfg, ids["scan 0042"], {"title": "Field Notes"})
    assert "Field Notes" not in {i["book"]["title"] for i in items(cfg, "filename_title")}


def test_titles_from_before_are_worked_out(cfg, shelf_lib):
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET title_from_name = NULL")
    assert items(cfg, "filename_title") == []  # not known yet
    check.check_files(cfg)
    assert "scan 0042" in {i["book"]["title"] for i in items(cfg, "filename_title")}


def test_duplicates(cfg, add):
    a = add("The Tale", authors=["A"])
    b = add("tale", authors=["a"])
    add("Tale", authors=["Someone Else"])
    add("The Tale", authors=["A"], series="Tales", index=2)
    dups = items(cfg, "duplicate")
    assert len(dups) == 1 and dups[0]["key"] == f"{min(a, b)},{max(a, b)}"
    assert {x["id"] for x in dups[0]["books"]} == {a, b}


def test_series_gaps(cfg, add):
    for n in (1, 2, 4, 6):
        add(f"Uprising {n}", series="Uprising", index=n)
    add("Uprising 2.5", series="Uprising", index=2.5)
    add("Lonely", series="Solo", index=3)
    gaps = items(cfg, "series_gap")
    assert [(g["key"], g["missing"]) for g in gaps] == [("Uprising", [3, 5])]


def test_scan_report_problems(cfg, make_calibre_db, tmp_path):
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 1, "title": "Here", "authors": ["A"]}, {"id": 2, "title": "Lost", "authors": ["B"]}])
    for p in root.rglob("*.pdf"):
        if "Lost" in str(p):
            p.unlink()
    cfg.books_dirs = [root, tmp_path / "gone"]
    scan(cfg)
    assert [i["key"] for i in items(cfg, "unreachable_folder")] == [str(tmp_path / "gone")]
    assert len(items(cfg, "calibre_missing")) == 1 and "Lost" in items(cfg, "calibre_missing")[0]["key"]
    assert check.problems(cfg)["last_scan"]["added"] == 1


def test_ignore_and_unignore(cfg, add):
    bid = add("Plain")
    assert any(i["kind"] == "no_cover" and i["key"] == str(bid) for i in items(cfg))
    check.ignore(cfg, "no_cover", str(bid))
    assert not any(i["kind"] == "no_cover" and i["key"] == str(bid) for i in items(cfg))
    assert check.problems(cfg)["ignored"] == 1
    assert check.list_ignored(cfg) == [{"kind": "no_cover", "key": str(bid)}]
    check.unignore(cfg, "no_cover", str(bid))
    assert check.problems(cfg)["ignored"] == 0
    with pytest.raises(ValueError):
        check.ignore(cfg, "made_up", "1")


def test_merge(cfg, add):
    sam = auth.create_user(cfg, "Sam", "longpassword")
    keep, other = add("The Tale"), add("Tale")
    with session(cfg.db_path) as con:
        other_file = con.execute("SELECT id FROM book_files WHERE book_id = ?", (other,)).fetchone()["id"]
    reading.save_progress(cfg, sam.id, other, file_id=other_file, page=3, pages=10)
    want = shelves.list_shelves(cfg, sam.id)[0]["id"]
    shelves.add(cfg, sam.id, want, other)
    shelves.add(cfg, sam.id, want, keep)
    library.merge_books(cfg, keep, other)
    b = library.get_book(cfg, keep, sam)
    assert len(b["files"]) == 2 and b["progress"]["page"] == 3 and b["shelves"] == [want]
    assert library.get_book(cfg, other) is None
    with pytest.raises(LookupError):
        library.merge_books(cfg, keep, 9999)
    with pytest.raises(ValueError):
        library.merge_books(cfg, keep, keep)


def test_check_routes(client, cfg):
    check.check_files(cfg)
    r = client.get("/api/check").json()
    assert {"protected"} <= {i["kind"] for i in r["items"]}
    item = next(i for i in r["items"] if i["kind"] == "protected")
    assert client.post("/api/check/ignored", json={"kind": item["kind"], "key": item["key"]}).status_code == 200
    assert client.get("/api/check").json()["ignored"] == 1
    assert client.get("/api/check/ignored").json() == [{"kind": item["kind"], "key": item["key"]}]
    assert client.request("DELETE", "/api/check/ignored", json={"kind": item["kind"], "key": item["key"]}).status_code == 200
    from test_api import book_id
    a, b = book_id(client, "Tale"), book_id(client, "Three Pages")
    assert client.post(f"/api/books/{a}/merge", json={"other": b}).status_code == 200
    assert client.get(f"/api/books/{b}").status_code == 404
    assert client.post(f"/api/books/{a}/merge", json={"other": a}).status_code == 400
    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    assert client.get("/api/check").status_code == 403
    assert client.post(f"/api/books/{a}/merge", json={"other": a}).status_code == 403

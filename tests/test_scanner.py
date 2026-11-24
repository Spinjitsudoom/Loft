from loft.db import session
from loft.scanner import ScanResult, scan


def books(cfg):
    with session(cfg.db_path) as con:
        return {r["title"]: dict(r) for r in con.execute("SELECT * FROM books")}


def library(cfg, make_calibre_db, make_cbz):
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 7, "title": "It", "authors": ["Stephen King"], "cover": True,
                            "tags": ["Horror"], "series": "Derry", "series_index": 1}])
    make_cbz(root / "Comics" / "Thing #1.cbz")
    (root / "Unknown" / "Passwords (155)").mkdir(parents=True)
    (root / "Unknown" / "Passwords (155)" / "Passwords - Unknown.docx").write_bytes(b"secret")
    (root / ".hidden.pdf").write_bytes(b"")
    return root


def test_scan_library(cfg, make_calibre_db, make_cbz):
    library(cfg, make_calibre_db, make_cbz)
    result = scan(cfg)
    assert result == ScanResult(added=2, updated=0, removed=0)
    b = books(cfg)
    assert set(b) == {"It", "Thing #1"}
    assert b["It"]["calibre_id"] == 7 and b["It"]["series"] == "Derry" and b["It"]["has_cover"] == 1
    assert b["Thing #1"]["has_cover"] == 1 and b["Thing #1"]["cover_color"].startswith("#")
    with session(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM books_fts WHERE books_fts MATCH 'derry'").fetchone()[0] == 1


def test_rescan_unchanged_is_noop(cfg, make_calibre_db, make_cbz):
    library(cfg, make_calibre_db, make_cbz)
    scan(cfg)
    assert scan(cfg) == ScanResult(0, 0, 0)


def test_changed_file_is_reread(cfg, make_calibre_db, make_cbz, make_pdf):
    root = library(cfg, make_calibre_db, make_cbz)
    p = make_pdf(root / "Loose" / "Fresh.pdf", title="Old Title")
    scan(cfg)
    make_pdf(p, title="New Title", pages=2)
    assert scan(cfg).updated == 1
    assert "New Title" in books(cfg) and "Old Title" not in books(cfg)


def test_removed_file(cfg, make_calibre_db, make_cbz):
    root = library(cfg, make_calibre_db, make_cbz)
    scan(cfg)
    book_id = books(cfg)["Thing #1"]["id"]
    (root / "Comics" / "Thing #1.cbz").unlink()
    assert scan(cfg).removed == 1
    assert "Thing #1" not in books(cfg)
    assert not list(cfg.cover_dir.glob(f"{book_id}-*"))


def test_unreachable_root_keeps_books(cfg, make_calibre_db, make_cbz):
    root = library(cfg, make_calibre_db, make_cbz)
    scan(cfg)
    root.rename(root.with_name("moved"))
    assert scan(cfg).removed == 0
    assert len(books(cfg)) == 2


def test_empty_root_keeps_books(cfg, make_calibre_db, make_cbz):
    """An SMB mount that drops can show up as an empty folder (the bare mount point)."""
    root = library(cfg, make_calibre_db, make_cbz)
    scan(cfg)
    root.rename(root.with_name("moved"))
    root.mkdir()
    assert scan(cfg).removed == 0
    assert len(books(cfg)) == 2


def test_broken_file_still_listed(cfg):
    (cfg.books_dirs[0] / "Broken Book.pdf").write_bytes(b"")
    assert scan(cfg).added == 1
    b = books(cfg)["Broken Book"]
    assert b["has_cover"] == 0


def test_loose_files_never_written(cfg, make_calibre_db, make_cbz):
    import os
    root = library(cfg, make_calibre_db, make_cbz)
    before = sorted((p, os.stat(os.path.join(p, f)).st_mtime_ns) for p, _, fs in os.walk(root) for f in fs)
    scan(cfg)
    after = sorted((p, os.stat(os.path.join(p, f)).st_mtime_ns) for p, _, fs in os.walk(root) for f in fs)
    assert before == after


def test_unreadable_subfolder_keeps_its_books(cfg, make_pdf):
    root = cfg.books_dirs[0]
    make_pdf(root / "Top.pdf")
    make_pdf(root / "Sub" / "A.pdf")
    make_pdf(root / "Sub" / "B.pdf")
    scan(cfg)
    ids = {t: b["id"] for t, b in books(cfg).items()}
    (root / "Sub").chmod(0)
    try:
        assert scan(cfg).removed == 0
        assert len(books(cfg)) == 3
    finally:
        (root / "Sub").chmod(0o755)
    assert scan(cfg) == ScanResult(0, 0, 0)
    assert {t: b["id"] for t, b in books(cfg).items()} == ids


def test_loose_file_becoming_calibre_leaves_no_orphan(cfg, make_calibre_db):
    import sqlite3
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 4, "title": "Leila", "authors": ["A. B."]}])
    con = sqlite3.connect(root / "metadata.db")
    con.execute("DELETE FROM data")  # Calibre hasn't recorded the file yet
    con.commit()
    scan(cfg)
    assert len(books(cfg)) == 1
    con.execute("INSERT INTO data(book, format, name) VALUES (4, 'PDF', 'Leila - A. B.')")
    con.commit()
    con.close()
    import os, time
    os.utime(root / "metadata.db", (time.time() + 5, time.time() + 5))
    scan(cfg)
    b = books(cfg)
    assert list(b) == ["Leila"] and b["Leila"]["calibre_id"] == 4


def test_failed_calibre_read_is_retried(cfg, make_calibre_db, monkeypatch):
    import loft.scanner as scanner_mod
    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 4, "title": "Leila", "authors": ["A. B."]}])
    real = scanner_mod.read_calibre
    monkeypatch.setattr(scanner_mod, "read_calibre", lambda r: None)  # e.g. Calibre mid-write
    scan(cfg)
    assert books(cfg) == {}  # not imported as a loose file with the wrong details
    monkeypatch.setattr(scanner_mod, "read_calibre", real)
    scan(cfg)
    assert books(cfg)["Leila"]["calibre_id"] == 4


def test_two_calibre_libraries_stay_apart(cfg, make_calibre_db, tmp_path):
    second = tmp_path / "books2"
    make_calibre_db(cfg.books_dirs[0], [{"id": 1, "title": "Dune", "authors": ["F. Herbert"]}])
    make_calibre_db(second, [{"id": 1, "title": "Saga Vol 1", "authors": ["B. K. Vaughan"]}])
    cfg.books_dirs.append(second)
    assert scan(cfg).added == 2
    assert set(books(cfg)) == {"Dune", "Saga Vol 1"}


def test_others_can_write_while_a_scan_runs(cfg, make_pdf, monkeypatch):
    """Creating the admin account during the first scan mustn't wait for (or time out on) the scan."""
    import sqlite3
    import loft.scanner as scanner_mod
    root = cfg.books_dirs[0]
    for name in ("A", "B", "C"):
        make_pdf(root / f"{name}.pdf")
    real = scanner_mod.extract_cover
    results = []

    def cover_and_write(path, fmt):
        con = sqlite3.connect(cfg.db_path, timeout=0.3)
        try:
            con.execute("INSERT INTO meta(key, value) VALUES (?, 'x')", (str(path),))
            con.commit()
            results.append(True)
        except sqlite3.OperationalError:
            results.append(False)
        finally:
            con.close()
        return real(path, fmt)

    monkeypatch.setattr(scanner_mod, "extract_cover", cover_and_write)
    scan(cfg)
    assert results == [True, True, True]


def test_scans_leave_locked_fields_alone(cfg, make_pdf):
    import json
    import os
    root = cfg.books_dirs[0]
    pdf = make_pdf(root / "Mine.pdf", title="From File", author="File Author")
    scan(cfg)
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET title = 'Admin Title', sort_title = 'Admin Title', locked = ?",
                    (json.dumps(["title"]),))
    st = pdf.stat()
    os.utime(pdf, (st.st_atime, st.st_mtime + 10))
    assert scan(cfg).updated == 1
    b = books(cfg)["Admin Title"]
    assert json.loads(b["authors"]) == ["File Author"]
    with session(cfg.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM books_fts WHERE books_fts MATCH 'admin'").fetchone()[0] == 1


def test_scan_stores_the_spine_palette(cfg, make_calibre_db, make_cbz):
    import re
    root = library(cfg, make_calibre_db, make_cbz)
    (root / "Broken Book.pdf").write_bytes(b"")      # no cover to be had
    scan(cfg)
    b = books(cfg)
    assert re.fullmatch(r"#[0-9a-f]{6} #[0-9a-f]{6}", b["It"]["spine_colors"])
    assert re.fullmatch(r"#[0-9a-f]{6} #[0-9a-f]{6}", b["Thing #1"]["spine_colors"])
    assert b["Broken Book"]["spine_colors"] is None

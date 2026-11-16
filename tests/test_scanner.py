from alcove.db import session
from alcove.scanner import ScanResult, scan


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

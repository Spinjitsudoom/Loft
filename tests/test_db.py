from loft.db import connect, session


def test_schema_created(tmp_path):
    con = connect(tmp_path / "f.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    for t in ("users", "books", "book_files", "books_fts", "meta"):
        assert t in names
    con.close()


def test_deleting_book_deletes_files(tmp_path):
    db = tmp_path / "f.db"
    with session(db) as con:
        con.execute("INSERT INTO books(id, title, sort_title, authors, tags, added_at, updated_at) "
                    "VALUES (1, 'T', 'T', '[]', '[]', 0, 0)")
        con.execute("INSERT INTO book_files(book_id, path, format, size, mtime, root) VALUES (1, '/x.pdf', 'pdf', 1, 0, '/')")
    with session(db) as con:
        con.execute("DELETE FROM books WHERE id = 1")
    with session(db) as con:
        assert con.execute("SELECT COUNT(*) FROM book_files").fetchone()[0] == 0


def test_session_rolls_back_on_error(tmp_path):
    db = tmp_path / "f.db"
    try:
        with session(db) as con:
            con.execute("INSERT INTO meta(key, value) VALUES ('a', 'b')")
            raise RuntimeError
    except RuntimeError:
        pass
    with session(db) as con:
        assert con.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0


def test_old_database_gains_new_columns(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE progress (user_id INTEGER, book_id INTEGER, file_id INTEGER, page INTEGER, pages INTEGER,
                               position REAL, finished INTEGER, updated_at REAL, PRIMARY KEY (user_id, book_id));
        INSERT INTO progress VALUES (1, 2, 3, 4, 10, 0.4, 0, 100.0);
        CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, user_id INTEGER, book_id INTEGER, file_id INTEGER,
                                page INTEGER, note TEXT, created_at REAL);
    """)
    con.commit()
    con.close()
    con = connect(db)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(progress)")}
    assert "locator" in cols
    assert "locator" in {r["name"] for r in con.execute("PRAGMA table_info(bookmarks)")}
    assert con.execute("SELECT page FROM progress").fetchone()["page"] == 4
    con.close()


def test_old_library_gains_m4_columns_and_tables(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL, sort_title TEXT NOT NULL,
                            series TEXT NOT NULL DEFAULT '', calibre_id INTEGER,
                            added_at REAL NOT NULL, updated_at REAL NOT NULL);
        INSERT INTO books(id, title, sort_title, added_at, updated_at) VALUES (1, 'It', 'It', 1, 1);
        CREATE TABLE book_files (id INTEGER PRIMARY KEY, book_id INTEGER, path TEXT, format TEXT, size INTEGER,
                                 mtime REAL, root TEXT);
        INSERT INTO book_files VALUES (1, 1, '/b/It.pdf', 'pdf', 1, 1, '/b');
    """)
    con.commit()
    con.close()
    con = connect(db)
    assert con.execute("SELECT locked FROM books").fetchone()["locked"] == "[]"
    row = con.execute("SELECT layout, layout_rev FROM book_files").fetchone()
    assert row["layout"] is None and row["layout_rev"] == 0
    tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"shelves", "shelf_books", "check_ignored", "file_checks"} <= tables
    con.close()


def test_a_new_library_opened_by_many_parts_at_once(tmp_path):
    # When Loft first starts, the scan, the update checker and the rest open the brand-new
    # database together; switching it to WAL used to fail for some with "database is locked".
    import threading
    failures = []
    for round_ in range(25):
        path, go, errors = tmp_path / f"{round_}" / "loft.db", threading.Event(), []
        def open_it():
            go.wait()
            try:
                connect(path).close()
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=open_it) for _ in range(6)]
        for t in threads:
            t.start()
        go.set()
        for t in threads:
            t.join()
        failures += errors
    assert failures == []


def test_old_library_gains_spine_colors(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT NOT NULL, sort_title TEXT NOT NULL,
                            authors TEXT NOT NULL DEFAULT '[]', author_sort TEXT NOT NULL DEFAULT '',
                            series TEXT NOT NULL DEFAULT '', series_index REAL, description TEXT NOT NULL DEFAULT '',
                            publisher TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '',
                            language TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', calibre_id INTEGER,
                            cover_color TEXT, has_cover INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL,
                            updated_at REAL NOT NULL, locked TEXT NOT NULL DEFAULT '[]', title_from_name INTEGER);
        INSERT INTO books(id, title, sort_title, cover_color, has_cover, added_at, updated_at)
            VALUES (1, 'It', 'It', '#402020', 1, 1, 1);
    """)
    con.commit()
    con.close()
    con = connect(db)
    assert "spine_colors" in {r["name"] for r in con.execute("PRAGMA table_info(books)")}
    assert con.execute("SELECT spine_colors FROM books").fetchone()["spine_colors"] is None
    con.close()

from alcove.db import connect, session


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

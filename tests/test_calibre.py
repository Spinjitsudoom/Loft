import os

from alcove.calibre import read_calibre

IT = {"id": 7, "title": "It", "authors": ["Stephen King"], "series": "Dark Tower", "series_index": 3,
      "tags": ["Horror", "Fiction"], "comment": "<p>Derry.</p><script>x()</script>", "publisher": "Viking",
      "pubdate": "1986-09-15 00:00:00+00:00", "language": "eng", "cover": True,
      "added": "2020-01-02 03:04:05.123456+00:00"}


def test_reads_calibre_book(tmp_path, make_calibre_db):
    root = make_calibre_db(tmp_path / "lib", [IT])
    books = read_calibre(root)
    pdf = root / "Stephen King" / "It (7)" / "It - Stephen King.pdf"
    assert list(books) == [pdf]
    b = books[pdf]
    assert (b.calibre_id, b.title, b.authors, b.author_sort) == (7, "It", ["Stephen King"], "Stephen King")
    assert (b.series, b.series_index) == ("Dark Tower", 3.0)
    assert b.tags == ["Horror", "Fiction"]
    assert b.description == "Derry."
    assert (b.publisher, b.published, b.language) == ("Viking", "1986-09-15", "eng")
    assert b.cover == root / "Stephen King" / "It (7)" / "cover.jpg"
    assert b.files == [pdf]
    assert b.added == 1577934245.123456


def test_placeholder_date_and_no_cover(tmp_path, make_calibre_db):
    root = make_calibre_db(tmp_path / "lib", [{"id": 1, "title": "Plain", "authors": ["A"]}])
    b = next(iter(read_calibre(root).values()))
    assert b.published == ""
    assert b.cover is None
    assert b.series == "" and b.series_index is None


def test_two_formats_one_book(tmp_path, make_calibre_db):
    root = make_calibre_db(tmp_path / "lib", [{"id": 3, "title": "Tide Line", "authors": ["J. Okafor"],
                                               "formats": ["EPUB", "PDF"]}])
    books = read_calibre(root)
    assert len(books) == 2
    a, b = books.values()
    assert a is b
    assert sorted(p.suffix for p in a.files) == [".epub", ".pdf"]


def test_missing_or_corrupt_db(tmp_path):
    assert read_calibre(tmp_path) == {}
    (tmp_path / "metadata.db").write_bytes(os.urandom(4096))
    assert read_calibre(tmp_path) is None  # there, but unreadable: try again later


def test_never_writes(tmp_path, make_calibre_db):
    root = make_calibre_db(tmp_path / "lib", [IT])
    before = sorted(os.listdir(root)), (root / "metadata.db").stat().st_mtime_ns
    read_calibre(root)
    assert (sorted(os.listdir(root)), (root / "metadata.db").stat().st_mtime_ns) == before


def test_unknown_author_is_no_author(tmp_path, make_calibre_db):
    root = make_calibre_db(tmp_path / "lib", [{"id": 2, "title": "Leila", "authors": ["Unknown"]}])
    assert next(iter(read_calibre(root).values())).authors == []

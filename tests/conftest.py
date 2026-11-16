import html
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

PAGE_COLOURS = {"page1.png": (200, 30, 30), "page2.png": (30, 200, 30), "page10.png": (30, 30, 200)}


def png(colour, size=(60, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


def jpg(colour, size=(60, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def make_pdf():
    def make(path: Path, *, title=None, author=None, pages=1, encrypt=False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        w = PdfWriter()
        for _ in range(pages):
            w.add_blank_page(width=300, height=450)
        meta = {}
        if title is not None:
            meta["/Title"] = title
        if author is not None:
            meta["/Author"] = author
        if meta:
            w.add_metadata(meta)
        if encrypt:
            w.encrypt(user_password="secret", owner_password="owner")
        with path.open("wb") as f:
            w.write(f)
        return path
    return make


@pytest.fixture
def make_epub():
    def make(path: Path, *, title, author, cover: bytes | None = None, series=None, series_index=None,
             description=None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = [f"<dc:title>{title}</dc:title>", f"<dc:creator>{author}</dc:creator>", "<dc:language>en</dc:language>"]
        if description:
            meta.append(f"<dc:description>{html.escape(description)}</dc:description>")
        if series:
            meta.append(f'<meta name="calibre:series" content="{series}"/>')
        if series_index is not None:
            meta.append(f'<meta name="calibre:series_index" content="{series_index}"/>')
        manifest = ['<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>']
        if cover:
            meta.append('<meta name="cover" content="cover-img"/>')
            manifest.append('<item id="cover-img" href="images/cover.jpg" media-type="image/jpeg"/>')
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">{''.join(meta)}</metadata>
  <manifest>{''.join(manifest)}</manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
        container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", container)
            z.writestr("OEBPS/content.opf", opf)
            z.writestr("OEBPS/c1.xhtml", "<html><body><p>Hello</p></body></html>")
            if cover:
                z.writestr("OEBPS/images/cover.jpg", cover)
        return path
    return make


@pytest.fixture
def make_cbz():
    def make(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for name in ("page10.png", "page2.png", "page1.png"):  # out of order on purpose
                z.writestr(name, png(PAGE_COLOURS[name]))
        return path
    return make


CALIBRE_SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, sort TEXT, author_sort TEXT, path TEXT,
                    has_cover BOOL DEFAULT 0, series_index REAL DEFAULT 1.0, pubdate TIMESTAMP);
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER);
CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT);
CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER);
CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, name TEXT);
"""


@pytest.fixture
def make_calibre_db(make_pdf, make_epub):
    """Write a Calibre-style library under root. Each book dict: id, title, authors, and optionally
    series, series_index, tags, comment, publisher, pubdate, language, formats (default ["PDF"]),
    cover (bool)."""
    import sqlite3

    def make(root: Path, books: list[dict]) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(root / "metadata.db")
        con.executescript(CALIBRE_SCHEMA)

        def ref(table, col, value):
            row = con.execute(f"SELECT id FROM {table} WHERE {col} = ?", (value,)).fetchone()
            return row[0] if row else con.execute(f"INSERT INTO {table}({col}) VALUES (?)", (value,)).lastrowid

        for b in books:
            author = b["authors"][0]
            folder = f"{author}/{b['title'][:30].replace(':', '_')} ({b['id']})"
            name = f"{b['title'][:30].replace(':', '_')} - {author}"
            con.execute("INSERT INTO books(id, title, sort, author_sort, path, has_cover, series_index, pubdate) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (b["id"], b["title"], b["title"], author, folder, int(b.get("cover", False)),
                         b.get("series_index", 1.0), b.get("pubdate", "0101-01-01 00:00:00+00:00")))
            for a in b["authors"]:
                con.execute("INSERT INTO books_authors_link(book, author) VALUES (?,?)", (b["id"], ref("authors", "name", a)))
            if b.get("series"):
                con.execute("INSERT INTO books_series_link(book, series) VALUES (?,?)", (b["id"], ref("series", "name", b["series"])))
            for t in b.get("tags", []):
                con.execute("INSERT INTO books_tags_link(book, tag) VALUES (?,?)", (b["id"], ref("tags", "name", t)))
            if b.get("comment"):
                con.execute("INSERT INTO comments(book, text) VALUES (?,?)", (b["id"], b["comment"]))
            if b.get("publisher"):
                con.execute("INSERT INTO books_publishers_link(book, publisher) VALUES (?,?)",
                            (b["id"], ref("publishers", "name", b["publisher"])))
            if b.get("language"):
                con.execute("INSERT INTO books_languages_link(book, lang_code) VALUES (?,?)",
                            (b["id"], ref("languages", "lang_code", b["language"])))
            for fmt in b.get("formats", ["PDF"]):
                con.execute("INSERT INTO data(book, format, name) VALUES (?,?,?)", (b["id"], fmt, name))
                f = root / folder / f"{name}.{fmt.lower()}"
                if fmt == "PDF":
                    make_pdf(f, title="ignored")
                else:
                    make_epub(f, title="ignored", author="ignored")
            if b.get("cover"):
                (root / folder / "cover.jpg").write_bytes(jpg((150, 40, 30), (300, 450)))
        con.commit()
        con.close()
        return root
    return make

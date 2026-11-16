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
    def make(path: Path, junk: bool = False) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for name in ("page10.png", "page2.png", "page1.png"):  # out of order on purpose
                z.writestr(name, png(PAGE_COLOURS[name]))
            if junk:
                z.writestr("__MACOSX/._page1.png", b"junk")
                z.writestr(".DS_Store", b"junk")
        return path
    return make


@pytest.fixture
def make_cb7(tmp_path_factory):
    import py7zr

    def make(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with py7zr.SevenZipFile(path, "w") as z:
            for name in ("page10.png", "page2.png", "page1.png"):
                z.writestr(png(PAGE_COLOURS[name]), name)
        return path
    return make


CALIBRE_SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, sort TEXT, author_sort TEXT, path TEXT,
                    has_cover BOOL DEFAULT 0, series_index REAL DEFAULT 1.0, pubdate TIMESTAMP,
                    timestamp TIMESTAMP);
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
            con.execute("INSERT INTO books(id, title, sort, author_sort, path, has_cover, series_index, pubdate, "
                        "timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                        (b["id"], b["title"], b["title"], author, folder, int(b.get("cover", False)),
                         b.get("series_index", 1.0), b.get("pubdate", "0101-01-01 00:00:00+00:00"),
                         b.get("added", "2024-05-01 10:00:00+00:00")))
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


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from alcove.config import load_config
    monkeypatch.setenv("ALCOVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ALCOVE_BOOKS_DIRS", raising=False)
    c = load_config(tmp_path / "none.toml")
    c.books_dirs = [tmp_path / "books"]
    c.books_dirs[0].mkdir()
    return c


@pytest.fixture
def app_lib(cfg, make_calibre_db, make_cbz, make_pdf, make_epub):
    """A small scanned library and an app over it (no one signed in yet)."""
    from fastapi.testclient import TestClient

    from alcove.app import create_app
    from alcove.scanner import scan

    root = cfg.books_dirs[0]
    make_calibre_db(root, [{"id": 7, "title": "It", "authors": ["Stephen King"], "cover": True,
                            "comment": "<p>Derry.</p><script>alert(1)</script>"}])
    make_cbz(root / "Comics" / "Tide Line.cbz")
    make_pdf(root / "Odd" / "Who's #1? odd.pdf")
    make_pdf(root / "Reader" / "Three Pages.pdf", title="Three Pages", pages=3)
    make_pdf(root / "Reader" / "Locked.pdf", title="Locked", encrypt=True)
    make_epub(root / "Reader" / "Tale.epub", title="Tale", author="A")
    scan(cfg)
    return TestClient(create_app(cfg, scan_on_start=False))


@pytest.fixture
def client(app_lib):
    """Signed in as the admin."""
    r = app_lib.post("/api/setup", json={"username": "admin", "password": "longpassword"})
    assert r.status_code == 200, r.text
    return app_lib


@pytest.fixture
def add(cfg):
    from alcove.db import session
    from alcove.scanner import _write_book

    counter = {"t": 1000.0}

    def add(title, authors=("A. Writer",), series="", index=None, tags=(), added=None, description=""):
        counter["t"] += 1
        with session(cfg.db_path) as con:
            bid = _write_book(con, None, title=title, authors=list(authors), author_sort="", series=series,
                              series_index=index, description=description, publisher="", published="", language="",
                              tags=list(tags), calibre_id=None, added_at=added or counter["t"])
            con.execute("INSERT INTO book_files(book_id, path, format, size, mtime, root) VALUES (?,?,?,?,?,?)",
                        (bid, f"/b/{bid}.pdf", "pdf", 10, 0, "/b"))
        return bid
    return add


@pytest.fixture
def make_rich_epub():
    """An EPUB with real chapters. chapters: [(href, body_html)] (hrefs relative to OEBPS/);
    spine: hrefs in reading order (default: chapter order); nav / ncx: [(title, target, level)];
    images: {href: bytes}; encryption: an algorithm URI for META-INF/encryption.xml."""
    def make(path: Path, *, chapters, spine=None, nav=None, ncx=None, images=None, encryption=None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        images = images or {}
        ids = {href: f"c{i}" for i, (href, _) in enumerate(chapters)}
        manifest = [f'<item id="{ids[h]}" href="{h}" media-type="application/xhtml+xml"/>' for h, _ in chapters]
        manifest += [f'<item id="img{i}" href="{h}" media-type="image/{"png" if h.endswith(".png") else "jpeg"}"/>'
                     for i, h in enumerate(images)]
        if nav is not None:
            manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        if ncx is not None:
            manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        spine_items = "".join(f'<itemref idref="{ids[h]}"/>' for h in (spine or [h for h, _ in chapters]))
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Rich</dc:title><dc:creator>A</dc:creator></metadata>
  <manifest>{"".join(manifest)}</manifest>
  <spine{' toc="ncx"' if ncx is not None else ''}>{spine_items}</spine>
</package>"""

        def tree(entries):
            """[(title, target, level)] → nested [(title, target, children)]."""
            root, stack = [], [(-1, None)]
            for title, target, level in entries:
                node = (title, target, [])
                while stack[-1][0] >= level:
                    stack.pop()
                (stack[-1][1][2] if stack[-1][1] else root).append(node)
                stack.append((level, node))
            return root

        def nested(entries):
            def ol(nodes):
                return "<ol>" + "".join(f'<li><a href="{t}">{title}</a>{ol(kids) if kids else ""}</li>'
                                        for title, t, kids in nodes) + "</ol>"
            return ol(tree(entries))

        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
            z.writestr("OEBPS/content.opf", opf)
            for href, body in chapters:
                z.writestr(f"OEBPS/{href}", f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                                           f"<head><title>x</title></head><body>{body}</body></html>")
            for href, data in images.items():
                z.writestr(f"OEBPS/{href}", data)
            if nav is not None:
                z.writestr("OEBPS/nav.xhtml", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                           'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc">'
                           f"{nested(nav)}</nav></body></html>")
            if ncx is not None:
                points, depth, out = 0, 0, ""
                for title, target, level in ncx:
                    while depth > level:
                        out += "</navPoint>"
                        depth -= 1
                    if out and depth == level:
                        out += "</navPoint>"
                    points += 1
                    out += (f'<navPoint id="p{points}"><navLabel><text>{title}</text></navLabel>'
                            f'<content src="{target}"/>')
                    depth = level
                out += "</navPoint>" * (depth + 1)
                z.writestr("OEBPS/toc.ncx", '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
                           f'version="2005-1"><navMap>{out}</navMap></ncx>')
            if encryption:
                z.writestr("META-INF/encryption.xml", '<?xml version="1.0"?><encryption '
                           'xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
                           f'<enc:EncryptedData><enc:EncryptionMethod Algorithm="{encryption}"/>'
                           '<enc:CipherData><enc:CipherReference URI="OEBPS/Text/one.xhtml"/></enc:CipherData>'
                           '</enc:EncryptedData></encryption>')
        return path
    return make

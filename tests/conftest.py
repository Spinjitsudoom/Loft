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

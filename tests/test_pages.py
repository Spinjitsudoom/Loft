import io
import os
import time

import pytest
from PIL import Image
from pypdf import PdfWriter

from alcove import pages
from alcove.db import session
from alcove.scanner import scan


def outline_pdf(path, sizes=((300, 450), (600, 450), (300, 450))):
    path.parent.mkdir(parents=True, exist_ok=True)
    w = PdfWriter()
    for width, height in sizes:
        w.add_blank_page(width=width, height=height)
    if len(sizes) >= 3:
        one = w.add_outline_item(title="Chapter One", page_number=0)
        w.add_outline_item(title="A part", page_number=1, parent=one)
        w.add_outline_item(title="Chapter Two", page_number=2)
    with path.open("wb") as f:
        w.write(f)
    return path


def file_id(cfg, name):
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE path LIKE ?", (f"%{name}",)).fetchone()["id"]


@pytest.fixture
def lib(cfg, make_cbz, make_pdf, make_epub):
    root = cfg.books_dirs[0]
    outline_pdf(root / "Book.pdf")
    make_cbz(root / "Comic.cbz")
    make_pdf(root / "Locked.pdf", title="Locked", encrypt=True)
    (root / "Broken.pdf").write_bytes(b"")
    make_epub(root / "Tale.epub", title="Tale", author="A")
    scan(cfg)
    return cfg


def test_pdf_manifest(lib):
    m = pages.manifest(lib, file_id(lib, "Book.pdf"))
    assert (m["format"], m["count"]) == ("pdf", 3)
    assert m["sizes"] == [[300, 450], [600, 450], [300, 450]]
    assert m["toc"] == [{"title": "Chapter One", "page": 0, "level": 0}, {"title": "A part", "page": 1, "level": 1},
                        {"title": "Chapter Two", "page": 2, "level": 0}]
    assert isinstance(m["version"], int)


def test_comic_manifest(lib):
    m = pages.manifest(lib, file_id(lib, "Comic.cbz"))
    assert (m["format"], m["count"], m["toc"]) == ("cbz", 3, [])
    assert m["sizes"] == [[60, 90]] * 3


def test_render_snaps_width_and_keeps_aspect(lib):
    p = pages.render_page(lib, file_id(lib, "Book.pdf"), 1, 1000)
    img = Image.open(p)
    assert img.size == (1200, 900)
    stamp = p.stat().st_mtime_ns
    assert pages.render_page(lib, file_id(lib, "Book.pdf"), 1, 1100) == p
    assert p.stat().st_mtime_ns == stamp


def test_render_out_of_range(lib):
    fid = file_id(lib, "Book.pdf")
    with pytest.raises(IndexError):
        pages.render_page(lib, fid, 3, 900)
    with pytest.raises(IndexError):
        pages.render_page(lib, fid, -1, 900)


def test_comics_are_not_upscaled(lib):
    p = pages.render_page(lib, file_id(lib, "Comic.cbz"), 0, 600)
    img = Image.open(p).convert("RGB")
    assert img.width == 60
    assert img.getpixel((3, 3)) == (200, 30, 30)  # page1.png comes first


def test_replaced_file_refreshes(lib):
    fid = file_id(lib, "Book.pdf")
    old = pages.render_page(lib, fid, 0, 900)
    path = lib.books_dirs[0] / "Book.pdf"
    outline_pdf(path, sizes=((300, 450), (300, 450)))
    later = time.time() + 10
    os.utime(path, (later, later))
    scan(lib)
    m = pages.manifest(lib, fid)
    assert m["count"] == 2
    new = pages.render_page(lib, fid, 0, 900)
    assert new != old and not old.parent.exists()


@pytest.mark.parametrize("name,kind", [("Locked.pdf", "protected"), ("Broken.pdf", "damaged"), ("Tale.epub", "format")])
def test_unreadable(lib, name, kind):
    with pytest.raises(pages.Unreadable) as e:
        pages.manifest(lib, file_id(lib, name))
    assert e.value.kind == kind


def test_unknown_file(lib):
    with pytest.raises(LookupError):
        pages.manifest(lib, 99999)


def test_prune(lib):
    pages.render_page(lib, file_id(lib, "Book.pdf"), 0, 900)
    lib.page_cache_mb = 0
    pages.prune_page_cache(lib)
    assert not any(p.is_file() for p in lib.page_dir.rglob("*"))


def spread_png(size=(160, 120)):
    """A two-page scan: left half red, right half blue."""
    img = Image.new("RGB", size, (200, 30, 30))
    img.paste((30, 30, 200), (size[0] // 2, 0, size[0], size[1]))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_scanned_spreads_are_split(cfg):
    import zipfile
    from conftest import png
    root = cfg.books_dirs[0]
    with zipfile.ZipFile(root / "Spreads.cbz", "w") as z:
        z.writestr("01.png", png((90, 90, 90), (80, 120)))  # the cover, a single page
        z.writestr("02.png", spread_png())
        z.writestr("03.png", spread_png())
    scan(cfg)
    fid = file_id(cfg, "Spreads.cbz")
    m = pages.manifest(cfg, fid)
    assert m["count"] == 5
    assert m["sizes"] == [[80, 120], [80, 120], [80, 120], [80, 120], [80, 120]]
    left = Image.open(pages.render_page(cfg, fid, 1, 600)).convert("RGB")
    right = Image.open(pages.render_page(cfg, fid, 2, 600)).convert("RGB")
    assert left.size == (80, 120)
    assert left.getpixel((40, 60))[0] > 150 and right.getpixel((40, 60))[2] > 150


def test_text_pdf_in_landscape_is_not_split(cfg):
    """Slides and landscape documents have real text: they stay whole."""
    from pypdf import PdfWriter
    from pypdf.generic import ContentStream, DecodedStreamObject, NameObject
    root = cfg.books_dirs[0]
    w = PdfWriter()
    for _ in range(3):
        page = w.add_blank_page(width=800, height=600)
        font = w._add_object(__import__("pypdf").generic.DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica")}))
        page[NameObject("/Resources")] = __import__("pypdf").generic.DictionaryObject({
            NameObject("/Font"): __import__("pypdf").generic.DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 24 Tf 72 500 Td (A slide with plenty of real words on it) Tj ET")
        page[NameObject("/Contents")] = w._add_object(stream)
    with (root / "Slides.pdf").open("wb") as f:
        w.write(f)
    scan(cfg)
    m = pages.manifest(cfg, file_id(cfg, "Slides.pdf"))
    assert m["count"] == 3 and m["sizes"][0] == [800, 600]


def test_toc_points_at_split_pages(cfg):
    """A scanned PDF (no text) of a cover plus two-page spreads: chapters land on the split pages."""
    outline_pdf(cfg.books_dirs[0] / "Scanned.pdf", sizes=((300, 450), (800, 560), (800, 560)))
    scan(cfg)
    m = pages.manifest(cfg, file_id(cfg, "Scanned.pdf"))
    assert m["count"] == 5
    assert [t["page"] for t in m["toc"]] == [0, 1, 3]

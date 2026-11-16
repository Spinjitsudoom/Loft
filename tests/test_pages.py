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

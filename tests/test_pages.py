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


def test_same_page_rendered_at_once(lib, monkeypatch):
    """The zoom view and a prefetch (or two readers) asking for one page together both get it."""
    import threading
    real_replace = os.replace

    def slow_replace(a, b):  # widen the window between writing a page and moving it into place
        time.sleep(0.05)
        real_replace(a, b)

    monkeypatch.setattr(pages.os, "replace", slow_replace)
    fid = file_id(lib, "Book.pdf")
    pages.manifest(lib, fid)
    errors, done = [], []

    def go():
        try:
            done.append(pages.render_page(lib, fid, 0, 2400))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    for _ in range(4):
        for p in lib.page_dir.rglob("0-2400.jpg"):
            p.unlink()
        threads = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    assert errors == [] and len(done) == 16
    assert Image.open(done[0]).width == 2400


def two_tone(left, right, size=(160, 120)):
    img = Image.new("RGB", size, left)
    img.paste(right, (size[0] // 2, 0, size[0], size[1]))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_wraparound_cover_front_first_back_last(cfg):
    import zipfile
    root = cfg.books_dirs[0]
    green, red, blue, gold = (30, 200, 30), (200, 30, 30), (30, 30, 200), (220, 180, 30)
    with zipfile.ZipFile(root / "Wrap.cbz", "w") as z:
        z.writestr("01.png", two_tone(green, red))   # back cover | front cover
        z.writestr("02.png", two_tone(blue, gold))
        z.writestr("03.png", two_tone(blue, gold))
    scan(cfg)
    fid = file_id(cfg, "Wrap.cbz")
    m = pages.manifest(cfg, fid)
    assert m["count"] == 6

    def colour(i):
        return Image.open(pages.render_page(cfg, fid, i, 600)).convert("RGB").getpixel((40, 60))

    def near(c, want):
        return all(abs(a - b) < 40 for a, b in zip(c, want))

    assert near(colour(0), red)       # the front cover comes first
    assert near(colour(1), blue) and near(colour(2), gold)
    assert near(colour(3), blue) and near(colour(4), gold)
    assert near(colour(5), green)     # the back cover comes last


def test_split_plan_switches():
    single, spread = [80, 120], [160, 120]
    mostly_single = [single, spread, single, single]
    assert len(pages.split_plan(mostly_single)) == 4
    assert pages.split_plan(mostly_single, split=True) == [(0, None), (1, 0), (1, 1), (2, None), (3, None)]
    assert pages.split_plan([spread, spread], scanned=False, split=True) == [(0, 1), (1, 0), (1, 1), (0, 0)]
    assert pages.split_plan([single, spread, spread], split=False) == [(0, None), (1, None), (2, None)]
    assert pages.split_plan([spread, spread, spread], wraparound=False) == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
    assert pages.split_plan([spread, spread, spread], wraparound=True) == pages.split_plan([spread, spread, spread])


def test_layout_switches_change_the_pages(cfg):
    import zipfile
    root = cfg.books_dirs[0]
    green, red, blue, gold = (30, 200, 30), (200, 30, 30), (30, 30, 200), (220, 180, 30)
    with zipfile.ZipFile(root / "Wrap.cbz", "w") as z:
        z.writestr("01.png", two_tone(green, red))
        z.writestr("02.png", two_tone(blue, gold))
        z.writestr("03.png", two_tone(blue, gold))
    scan(cfg)
    fid = file_id(cfg, "Wrap.cbz")
    before = pages.manifest(cfg, fid)
    m = pages.set_layout(cfg, fid, None, False)
    assert m["version"] != before["version"] and m["count"] == 6
    first = Image.open(pages.render_page(cfg, fid, 0, 600)).convert("RGB").getpixel((40, 60))
    assert first[1] > 150  # the scan's left half (green) comes first now
    m = pages.set_layout(cfg, fid, False, None)
    assert m["count"] == 3 and pages.manifest(cfg, fid)["count"] == 3


def test_layout_only_for_page_books(cfg, make_epub):
    make_epub(cfg.books_dirs[0] / "Tale.epub", title="Tale", author="A")
    scan(cfg)
    with pytest.raises(ValueError):
        pages.set_layout(cfg, file_id(cfg, "Tale.epub"), True, None)


def test_layout_route(client):
    from test_api import book_id
    b = client.get(f"/api/books/{book_id(client, 'Tide Line')}").json()
    f = b["files"][0]
    assert f["layout"] == {"split": None, "wraparound": None}
    r = client.patch(f"/api/files/{f['id']}/layout", json={"split": True, "wraparound": None})
    assert r.status_code == 200 and r.json()["count"] == 3
    b = client.get(f"/api/books/{b['id']}").json()
    assert b["files"][0]["layout"] == {"split": True, "wraparound": None}
    tale = client.get(f"/api/books/{book_id(client, 'Tale')}").json()["files"][0]
    assert "layout" not in tale
    assert client.patch(f"/api/files/{tale['id']}/layout", json={"split": True}).status_code == 400
    assert client.patch("/api/files/9999/layout", json={"split": True}).status_code == 404

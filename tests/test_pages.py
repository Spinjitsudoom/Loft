import io
import json
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
        for p in lib.page_dir.rglob("*-2400.jpg"):
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
    assert f["layout"] == {"split": None, "wraparound": None, "rtl": False}
    r = client.patch(f"/api/files/{f['id']}/layout", json={"split": True, "wraparound": None})
    assert r.status_code == 200 and r.json()["count"] == 3
    b = client.get(f"/api/books/{b['id']}").json()
    assert b["files"][0]["layout"] == {"split": True, "wraparound": None, "rtl": False}
    r = client.patch(f"/api/files/{f['id']}/layout", json={"split": True, "wraparound": None, "rtl": True})
    assert r.status_code == 200 and r.json()["rtl"] is True
    assert client.get(f"/api/books/{b['id']}").json()["files"][0]["layout"] == {"split": True, "wraparound": None,
                                                                               "rtl": True}
    tale = client.get(f"/api/books/{book_id(client, 'Tale')}").json()["files"][0]
    assert "layout" not in tale
    assert client.patch(f"/api/files/{tale['id']}/layout", json={"split": True}).status_code == 400
    assert client.patch("/api/files/9999/layout", json={"split": True}).status_code == 404


def test_manga_split_plan_reads_right_to_left():
    single, spread = [80, 120], [160, 120]
    # A manga's two-page scan has the earlier page on the right.
    assert pages.split_plan([single, spread, spread], rtl=True) == [(0, None), (1, 1), (1, 0), (2, 1), (2, 0)]
    # Its wraparound cover has the front on the left half (the spine is on the right).
    assert pages.split_plan([spread, spread, spread], rtl=True) == [(0, 0), (1, 1), (1, 0), (2, 1), (2, 0), (0, 1)]
    assert pages.split_plan([spread, spread], wraparound=False, rtl=True) == [(0, 1), (0, 0), (1, 1), (1, 0)]
    assert pages.split_plan([single, single], rtl=True) == [(0, None), (1, None)]


def test_right_to_left_switch_turns_the_pages(cfg):
    import zipfile
    root = cfg.books_dirs[0]
    green, red, blue, gold = (30, 200, 30), (200, 30, 30), (30, 30, 200), (220, 180, 30)
    with zipfile.ZipFile(root / "Manga.cbz", "w") as z:
        z.writestr("01.png", two_tone(green, red))
        z.writestr("02.png", two_tone(blue, gold))
        z.writestr("03.png", two_tone(blue, gold))
    scan(cfg)
    fid = file_id(cfg, "Manga.cbz")

    def colour(i):
        return Image.open(pages.render_page(cfg, fid, i, 600)).convert("RGB").getpixel((40, 60))

    before = pages.manifest(cfg, fid)
    assert before["rtl"] is False and colour(1)[2] > 150   # left to right: the blue (left) half first
    m = pages.set_layout(cfg, fid, None, None, rtl=True)
    assert m["rtl"] is True and m["version"] != before["version"] and m["count"] == 6
    assert colour(0)[1] > 150                            # the front cover is the scan's left half (green)
    assert colour(1)[0] > 150 and colour(1)[1] > 120     # then the right half (gold) of each spread
    assert colour(2)[2] > 150
    assert colour(5)[0] > 150 and colour(5)[1] < 100     # the back cover (red) is last
    # Changing another switch leaves the direction alone.
    assert pages.set_layout(cfg, fid, True, None)["rtl"] is True
    assert pages.set_layout(cfg, fid, None, None, rtl=False)["rtl"] is False and colour(1)[2] > 150


def test_a_damaged_files_layout_still_saves(lib):
    # The change is kept even though the file can't be opened to show its pages; saying it failed
    # would leave the buttons on the old choice until a refresh.
    fid = file_id(lib, "Broken.pdf")
    reply = pages.set_layout(lib, fid, None, None, rtl=True)
    assert reply["rtl"] is True and reply["count"] is None
    with session(lib.db_path) as con:
        row = con.execute("SELECT layout FROM book_files WHERE id = ?", (fid,)).fetchone()
    assert json.loads(row["layout"])["rtl"] is True


def test_changing_the_layout_doesnt_read_the_file_again(cfg, monkeypatch):
    # A big comic on a network share takes seconds to measure; its page sizes are already known.
    import zipfile
    with zipfile.ZipFile(cfg.books_dirs[0] / "Manga.cbz", "w") as z:
        z.writestr("01.png", spread_png())
        z.writestr("02.png", spread_png())
    scan(cfg)
    fid = file_id(cfg, "Manga.cbz")
    assert pages.manifest(cfg, fid)["count"] == 4

    def measured_again(*a):
        raise AssertionError("the file was read again")
    monkeypatch.setattr(pages, "_comic_manifest", measured_again)
    m = pages.set_layout(cfg, fid, False, None, rtl=True)
    assert m["count"] == 2 and m["rtl"] is True
    m = pages.set_layout(cfg, fid, None, None, rtl=True)
    assert m["count"] == 4 and m["plan"] == [[0, 0], [1, 1], [1, 0], [0, 1]]
    assert pages.manifest(cfg, fid)["plan"] == m["plan"]


# ---------- arranging pages by hand ----------

COLOURS = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 180, 30), (160, 30, 160)]


def five_page_comic(cfg):
    import zipfile
    from conftest import png
    with zipfile.ZipFile(cfg.books_dirs[0] / "Five.cbz", "w") as z:
        for i, c in enumerate(COLOURS):
            z.writestr(f"{i + 1:02}.png", png(c, (400, 600)))
    scan(cfg)
    return file_id(cfg, "Five.cbz")


def shown(cfg, fid, i):
    return Image.open(pages.render_page(cfg, fid, i, 600)).convert("RGB").getpixel((20, 20))


def near(a, b):
    return all(abs(x - y) < 40 for x, y in zip(a, b))


def test_arrange_reconciles_an_order_with_the_pages():
    whole = [(0, None), (1, None), (2, None), (3, None)]
    assert pages.arrange(whole, None, []) == (whole, whole, [])
    order = [(3, None), (0, None), (1, None), (2, None)]
    assert pages.arrange(whole, order, [(1, None)]) == (
        [(3, None), (0, None), (2, None)], order, [(1, None)])
    # Split turned on after page 2 was moved to the front: both its halves come with it.
    split = [(0, None), (1, None), (2, 0), (2, 1), (3, None)]
    assert pages.arrange(split, [(2, None), (0, None), (1, None), (3, None)], [])[0] == \
        [(2, 0), (2, 1), (0, None), (1, None), (3, None)]
    # A whole page hidden hides both its halves; both halves hidden hides the whole page.
    assert pages.arrange(split, None, [(2, None)])[0] == [(0, None), (1, None), (3, None)]
    assert pages.arrange(whole, None, [(2, 0), (2, 1)])[0] == [(0, None), (1, None), (3, None)]
    # A page the order doesn't know (the file grew) lands after the page before it.
    grown = whole + [(4, None)]
    assert pages.arrange(grown, order, [])[0] == [(3, None), (4, None), (0, None), (1, None), (2, None)]
    # Everything hidden would leave nothing to read: nothing is hidden then.
    assert pages.arrange(whole, None, whole)[0] == whole


def test_arranging_pages_by_hand(cfg):
    fid = five_page_comic(cfg)
    m = pages.set_arrangement(cfg, fid, [[4, None], [0, None], [1, None], [2, None], [3, None]], [[2, None]])
    assert m["plan"] == [[4, None], [0, None], [1, None], [3, None]] and m["count"] == 4
    assert m["arranged"] == [[4, None], [0, None], [1, None], [2, None], [3, None]]
    assert m["hidden"] == [[2, None]]
    assert near(shown(cfg, fid, 0), COLOURS[4]) and near(shown(cfg, fid, 3), COLOURS[3])

    # The other page settings keep the arrangement.
    m = pages.set_layout(cfg, fid, None, None, rtl=True)
    assert m["plan"] == [[4, None], [0, None], [1, None], [3, None]] and m["rtl"] is True

    m = pages.set_arrangement(cfg, fid, None, [])
    assert m["plan"] == [[i, None] for i in range(5)] and m["hidden"] == []


def test_arranging_checks_what_it_is_given(cfg):
    fid = five_page_comic(cfg)
    every = [[i, None] for i in range(5)]
    for order, hidden in [
        (every[:4], []),                              # a page missing
        (every + [[0, None]], []),                    # a page twice
        ([[0, 1]] + every[1:], []),                   # a half that isn't there
        (every, [[9, None]]),                         # hiding a page that isn't there
        (every, every),                               # hiding every page
        ([[0, "x"]] + every[1:], []),                 # not a page at all
    ]:
        with pytest.raises(ValueError):
            pages.set_arrangement(cfg, fid, order, hidden)


def test_moving_pages_doesnt_draw_them_again(cfg):
    fid = five_page_comic(cfg)
    first = pages.render_page(cfg, fid, 4, 600)
    pages.set_arrangement(cfg, fid, [[4, None]] + [[i, None] for i in range(4)], [])
    assert pages.render_page(cfg, fid, 0, 600) == first and first.is_file()
    thumb = pages.render_piece(cfg, fid, 4, None, 200)
    assert Image.open(thumb).width == 200
    with pytest.raises(IndexError):
        pages.render_piece(cfg, fid, 4, 0, 200)


def test_arrangement_routes(client, cfg):
    fid = five_page_comic(cfg)
    order = [[4, None]] + [[i, None] for i in range(4)]
    r = client.patch(f"/api/files/{fid}/arrangement", json={"order": order, "hidden": [[1, None]]})
    assert r.status_code == 200 and r.json()["count"] == 4
    book = client.get(f"/api/books/{client.get('/api/search?q=Five').json()[0]['id']}").json()
    assert book["files"][0]["arranged"] is True
    assert client.get(f"/api/files/{fid}/piece?src=1&w=200").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/files/{fid}/piece?src=1&half=0&w=200").status_code == 404
    assert client.patch(f"/api/files/{fid}/arrangement", json={"order": order[:2], "hidden": []}).status_code == 400
    assert client.patch(f"/api/files/{fid}/arrangement", json={"order": None, "hidden": []}).json()["count"] == 5

    client.post("/api/users", json={"username": "sam", "password": "samsamsam"})
    client.post("/api/login", json={"username": "sam", "password": "samsamsam"})
    assert client.patch(f"/api/files/{fid}/arrangement", json={"order": None, "hidden": []}).status_code == 403
    assert client.get(f"/api/files/{fid}/piece?src=1&w=200").status_code == 403


def test_blank_pages(cfg):
    # A blank behind a cover keeps the two-page spreads that follow on their pairs, as in print.
    fid = five_page_comic(cfg)
    order = [[4, None], [-1, None]] + [[i, None] for i in range(4)]
    m = pages.set_arrangement(cfg, fid, order, [])
    assert m["plan"] == order and m["count"] == 6
    assert m["sizes"][1] == m["sizes"][0]                       # as big as the page before it
    blank = Image.open(pages.render_page(cfg, fid, 1, 600)).convert("RGB")
    assert blank.getpixel((20, 20)) == (255, 255, 255) and blank.size == (600, 900)  # the page shape, 2:3
    assert Image.open(pages.render_piece(cfg, fid, -1, None, 200)).width == 200
    # Blanks stay where they were put when other settings change.
    assert pages.set_layout(cfg, fid, None, None, rtl=True)["plan"] == order
    with pytest.raises(ValueError):
        pages.set_arrangement(cfg, fid, order, [[-1, None]])    # a blank is removed, not hidden
    with pytest.raises(ValueError):
        pages.set_arrangement(cfg, fid, order + [[-1, None]], [])
    with pytest.raises(ValueError):
        pages.set_arrangement(cfg, fid, [[i, None] for i in range(5)] + [[-2, 0]], [])  # blanks are whole pages
    assert pages.set_arrangement(cfg, fid, None, [])["count"] == 5


def test_arrange_keeps_blanks_in_place():
    whole = [(0, None), (1, None), (2, None)]
    order = [(0, None), (-1, None), (1, None), (2, None)]
    assert pages.arrange(whole, order, [])[0] == order
    split = [(0, None), (1, 0), (1, 1), (2, None)]
    assert pages.arrange(split, order, [])[0] == [(0, None), (-1, None), (1, 0), (1, 1), (2, None)]

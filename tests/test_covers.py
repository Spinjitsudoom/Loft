import colorsys
import io
import re

import pytest
from PIL import Image

from loft import covers
from loft.covers import cover_path, extract_cover, fill_spines, spine_colours, spine_palette, store_cover
from loft.db import session
from conftest import jpg


def test_epub_cover(tmp_path, make_epub):
    p = make_epub(tmp_path / "a.epub", title="T", author="A", cover=jpg((10, 120, 200)))
    img = Image.open(io.BytesIO(extract_cover(p, "epub"))).convert("RGB")
    r, g, b = img.getpixel((5, 5))
    assert b > 150 and r < 60


def test_pdf_cover_renders_first_page(tmp_path, make_pdf):
    p = make_pdf(tmp_path / "a.pdf", pages=2)
    img = Image.open(io.BytesIO(extract_cover(p, "pdf")))
    assert img.width == 600
    assert abs(img.height / img.width - 1.5) < 0.01


def test_cbz_cover_is_first_page_in_natural_order(tmp_path, make_cbz):
    p = make_cbz(tmp_path / "a.cbz")
    img = Image.open(io.BytesIO(extract_cover(p, "cbz"))).convert("RGB")
    assert img.getpixel((5, 5)) == (200, 30, 30)  # page1.png, not page10.png


@pytest.mark.parametrize("fmt,data", [("pdf", b""), ("epub", b"junk"), ("cbz", b"junk"), ("mobi", b"x")])
def test_unreadable_gives_none(tmp_path, fmt, data):
    p = tmp_path / f"x.{fmt}"
    p.write_bytes(data)
    assert extract_cover(p, fmt) is None


def test_store_cover_sizes_and_colour(cfg):
    colour = store_cover(cfg, 5, jpg((230, 200, 150), (600, 900)))
    for w in (480, 240):
        f = cover_path(cfg, 5, w)
        assert Image.open(f).width == w
    assert cover_path(cfg, 5, 300) == cover_path(cfg, 5, 240)
    assert cover_path(cfg, 5, 1000) == cover_path(cfg, 5, 480)
    assert cover_path(cfg, 6, 240) is None
    assert re.fullmatch(r"#[0-9a-f]{6}", colour)
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    assert colorsys.rgb_to_hls(r, g, b)[1] <= 0.30 + 1e-6


def _hex(s): return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
def _near(a, b, tol=30): return all(abs(x - y) <= tol for x, y in zip(_hex(a), b))


def test_spine_palette_takes_the_covers_two_colours():
    img = Image.new("RGB", (60, 90), (160, 20, 20))
    img.paste((230, 190, 60), (0, 60, 60, 90))           # a third of it gold
    base, accent = spine_palette(img).split()
    assert _near(base, (160, 20, 20)) and _near(accent, (230, 190, 60))


def test_one_colour_cover_gets_a_deep_shade_for_its_label():
    base, accent = spine_palette(Image.new("RGB", (60, 90), (40, 90, 160))).split()
    assert _near(base, (40, 90, 160))
    assert _near(accent, (18, 40, 72), tol=4)             # base × 0.45


def test_white_cover_gives_a_light_spine():
    base, _ = spine_palette(Image.new("RGB", (60, 90), (245, 240, 230))).split()
    assert min(_hex(base)) > 200                          # not capped dark like cover_color


@pytest.mark.parametrize("img", [
    Image.new("L", (60, 90), 128),
    Image.new("RGBA", (60, 90), (10, 200, 10, 0)).convert("P"),
    Image.new("RGB", (1, 1), (9, 9, 9)),
])
def test_odd_images_still_give_a_palette(img):
    assert re.fullmatch(r"#[0-9a-f]{6} #[0-9a-f]{6}", spine_palette(img))


def test_spine_colours_reads_the_stored_cover(cfg):
    assert spine_colours(cfg, 7) is None
    store_cover(cfg, 7, jpg((160, 20, 20), (600, 900)))
    assert _near(spine_colours(cfg, 7).split()[0], (160, 20, 20))
    (cfg.cover_dir / "7-480.jpg").write_bytes(b"junk")
    assert spine_colours(cfg, 7) is None


def rows(cfg):
    with session(cfg.db_path) as con:
        return [dict(r) for r in con.execute("SELECT id, spine_colors FROM books ORDER BY id")]


def test_fill_spines_fills_books_missing_a_palette(cfg, add):
    a, b, c = add("A"), add("B"), add("C")
    for bid in (a, b):
        store_cover(cfg, bid, jpg((160, 20, 20), (600, 900)))
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET has_cover = 1 WHERE id IN (?, ?, ?)", (a, b, c))   # c: cover file missing
        con.execute("UPDATE books SET spine_colors = '#010101 #020202' WHERE id = ?", (b,))
    assert fill_spines(cfg, batch=1) == 1
    spines = {r["id"]: r["spine_colors"] for r in rows(cfg)}
    assert re.fullmatch(r"#[0-9a-f]{6} #[0-9a-f]{6}", spines[a])
    assert spines[b] == "#010101 #020202"     # already filled: left alone
    assert spines[c] is None                  # no cover file: skipped, no error
    assert fill_spines(cfg) == 0              # nothing left; c isn't retried forever in one run


def test_fill_spines_skips_a_cover_cleared_meanwhile(cfg, add, monkeypatch):
    a = add("A")
    store_cover(cfg, a, jpg((160, 20, 20), (600, 900)))
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET has_cover = 1 WHERE id = ?", (a,))
    real = covers.spine_colours

    def clear_then_read(cfg_, bid):
        with session(cfg.db_path) as con:
            con.execute("UPDATE books SET has_cover = 0, cover_color = NULL WHERE id = ?", (bid,))
        return real(cfg_, bid)
    monkeypatch.setattr(covers, "spine_colours", clear_then_read)
    fill_spines(cfg)
    assert rows(cfg)[0]["spine_colors"] is None


def test_spine_filler_runs_in_the_background(cfg, add):
    a = add("A")
    store_cover(cfg, a, jpg((160, 20, 20), (600, 900)))
    with session(cfg.db_path) as con:
        con.execute("UPDATE books SET has_cover = 1 WHERE id = ?", (a,))
    filler = covers.SpineFiller(cfg)
    filler.start()
    filler._thread.join(10)
    assert filler._thread.name == "loft-spines" and filler._thread.daemon
    assert rows(cfg)[0]["spine_colors"]

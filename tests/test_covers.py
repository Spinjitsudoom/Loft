import colorsys
import io
import re

import pytest
from PIL import Image

from loft.covers import cover_path, extract_cover, store_cover
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

import io
from pathlib import Path

import pytest
from PIL import Image

from loft import comics
from loft.covers import extract_cover
from conftest import PAGE_COLOURS

ORDER = ["page1.png", "page2.png", "page10.png"]


def colour(data: bytes):
    return Image.open(io.BytesIO(data)).convert("RGB").getpixel((3, 3))


def test_cbz(tmp_path, make_cbz):
    p = make_cbz(tmp_path / "a.cbz", junk=True)
    assert comics.archive_kind(p) == "zip"
    assert comics.page_names(p) == ORDER
    assert colour(comics.read_member(p, "page2.png")) == PAGE_COLOURS["page2.png"]


def test_cb7(tmp_path, make_cb7):
    p = make_cb7(tmp_path / "a.cb7")
    assert comics.archive_kind(p) == "7z"
    assert comics.page_names(p) == ORDER
    assert colour(comics.read_member(p, "page10.png")) == PAGE_COLOURS["page10.png"]


def test_mislabelled_cbr_is_read_as_zip(tmp_path, make_cbz):
    p = make_cbz(tmp_path / "a.cbz").rename(tmp_path / "really-a-zip.cbr")
    assert comics.archive_kind(p) == "zip"
    assert comics.page_names(p) == ORDER
    assert colour(extract_cover(p, "cbr")) == PAGE_COLOURS["page1.png"]


def test_cb7_cover(tmp_path, make_cb7):
    assert colour(extract_cover(make_cb7(tmp_path / "a.cb7"), "cb7")) == PAGE_COLOURS["page1.png"]


def test_garbage(tmp_path):
    p = tmp_path / "x.cbz"
    p.write_bytes(b"this is not an archive")
    assert comics.archive_kind(p) is None
    with pytest.raises(comics.ComicError):
        comics.page_names(p)
    with pytest.raises(comics.ComicError):
        comics.read_member(p, "page1.png")


SAMPLE_RAR = Path(__file__).parent / "data" / "sample.cbr"


@pytest.mark.skipif(not SAMPLE_RAR.exists(), reason="no RAR sample (making one needs the non-free rar tool)")
def test_real_rar():
    assert comics.archive_kind(SAMPLE_RAR) == "rar"
    assert comics.page_names(SAMPLE_RAR)

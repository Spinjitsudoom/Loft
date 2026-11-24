import struct
from pathlib import Path

import pytest

from loft.filemeta import read_file_meta, title_from_filename


def test_pdf_title_author(tmp_path, make_pdf):
    p = make_pdf(tmp_path / "x.pdf", title="The Long Road", author="A. Marlow; B. Field")
    m = read_file_meta(p, "pdf")
    assert m.title == "The Long Road"
    assert m.authors == ["A. Marlow", "B. Field"]
    assert m.encrypted is False


@pytest.mark.parametrize("junk", ["Microsoft Word - draft.doc", "untitled", "Untitled1", "   ", "Fernwood - J. Okafor",
                                  "layout_final.indd"])
def test_pdf_junk_title_uses_filename(tmp_path, make_pdf, junk):
    p = make_pdf(tmp_path / "J. Okafor" / "Fernwood (12)" / "Fernwood - J. Okafor.pdf", title=junk)
    assert read_file_meta(p, "pdf").title == "Fernwood"


def test_pdf_without_metadata_uses_filename(tmp_path, make_pdf):
    p = make_pdf(tmp_path / "#03 Assassin's Creed - The Secret Crusade.pdf")
    assert read_file_meta(p, "pdf").title == "#03 Assassin's Creed - The Secret Crusade"


def test_calibre_style_filename():
    assert title_from_filename(Path("Alex Paknadel/Assassin's Creed_ Uprising #1 (59)/Assassin's Creed_ Uprising #1 - Alex Paknadel.pdf")) == "Assassin's Creed: Uprising #1"
    assert title_from_filename(Path("Some_File_Name.pdf")) == "Some File Name"


def test_epub_details(tmp_path, make_epub):
    p = make_epub(tmp_path / "t.epub", title="Tide Line", author="J. Okafor", series="Coast", series_index=2,
                  description="<p>A sea story.</p>")
    m = read_file_meta(p, "epub")
    assert (m.title, m.authors, m.series, m.series_index) == ("Tide Line", ["J. Okafor"], "Coast", 2.0)
    assert m.language == "en"
    assert m.description == "A sea story."


def test_broken_files_never_raise(tmp_path):
    empty = tmp_path / "Empty Book.pdf"
    empty.write_bytes(b"")
    garbage = tmp_path / "Garbage Book.epub"
    garbage.write_bytes(b"\x00not a zip at all")
    assert read_file_meta(empty, "pdf").title == "Empty Book"
    assert read_file_meta(garbage, "epub").title == "Garbage Book"


def test_encrypted_pdf_flagged(tmp_path, make_pdf):
    p = make_pdf(tmp_path / "Locked.pdf", title="Locked", encrypt=True)
    m = read_file_meta(p, "pdf")
    assert m.encrypted is True
    assert m.title == "Locked"


def test_other_formats_use_filename(tmp_path):
    p = tmp_path / "Someone" / "Thing #1 (4)" / "Thing #1 - Someone.cbz"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"")
    assert read_file_meta(p, "cbz").title == "Thing #1"


def test_dash_kept_outside_calibre_folders():
    assert title_from_filename(Path("Comics/Assassin's Creed - The Chain.pdf")) == "Assassin's Creed - The Chain"


def test_html_to_text():
    from loft.calibre import html_to_text
    assert html_to_text('<p>One &amp; two</p><script>alert(1)</script><p>Three<br>four</p>') == "One & two\n\nThree\nfour"
    assert html_to_text('<div><p style="x">A  <b>bold</b>\n move</p></div>') == "A bold move"
    assert html_to_text("") == ""


@pytest.mark.parametrize("junk", ["327842\x00", "12345", "www.example.com", "PDFDrive.com"])
def test_more_junk_titles(tmp_path, make_pdf, junk):
    p = make_pdf(tmp_path / "#03 Assassin's Creed - The Secret Crusade.pdf", title=junk)
    assert read_file_meta(p, "pdf").title == "#03 Assassin's Creed - The Secret Crusade"


def test_title_cleanup(tmp_path, make_pdf):
    p = make_pdf(tmp_path / "x.pdf", title="Assassin\\'s Creed The Secret Crusade - PDFDrive.com")
    assert read_file_meta(p, "pdf").title == "Assassin's Creed The Secret Crusade"
    p = make_pdf(tmp_path / "y.pdf", title="Tide\x00 Line\x07")
    assert read_file_meta(p, "pdf").title == "Tide Line"


@pytest.mark.parametrize("placeholder", ["Unknown", "unknown author", "Unknown Authors"])
def test_placeholder_author_dropped(tmp_path, make_pdf, placeholder):
    p = make_pdf(tmp_path / "x.pdf", title="Real Title", author=placeholder)
    assert read_file_meta(p, "pdf").authors == []


def kindle_file(path: Path, *, title="", exth=(), encoding=65001) -> Path:
    """A minimal MOBI/AZW3: a PalmDB header, then record 0 with the PalmDOC and MOBI headers, the
    full name and (when given) an EXTH block of (type, bytes) records."""
    exth_block = b""
    if exth:
        records = b"".join(struct.pack(">II", t, 8 + len(v)) + v for t, v in exth)
        exth_block = b"EXTH" + struct.pack(">II", 12 + len(records), len(exth)) + records
    mobi_len = 0xE8
    name = title.encode("utf-8" if encoding == 65001 else "cp1252")
    name_at = 16 + mobi_len + len(exth_block)
    mobi = bytearray(mobi_len)
    mobi[0:4] = b"MOBI"
    struct.pack_into(">I", mobi, 4, mobi_len)
    struct.pack_into(">I", mobi, 12, encoding)
    struct.pack_into(">II", mobi, 0x54 - 16, name_at, len(name))
    struct.pack_into(">I", mobi, 0x80 - 16, 0x40 if exth else 0)
    record0 = bytes(16) + bytes(mobi) + exth_block + name + bytes(4)
    header = bytearray(78)
    header[0:10] = b"some-name\0"
    header[60:68] = b"BOOKMOBI"
    struct.pack_into(">H", header, 76, 1)
    first = 78 + 8 + 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + struct.pack(">II", first, 0) + bytes(2) + record0)
    return path


@pytest.mark.parametrize("fmt", ["azw3", "mobi", "azw"])
def test_kindle_details(tmp_path, fmt):
    p = kindle_file(tmp_path / f"54812911c00c8f82bb1fb0a81d6a3b03.{fmt}", title="Short Name", exth=[
        (503, "The Mouse Island Marathon".encode()), (100, b"Stilton, Geronimo"), (100, b"Elisabetta Dami"),
        (101, b"Scholastic Inc."), (106, b"2011-11-01T00:00:00+00:00"), (524, b"en"),
        (103, b"<p>A <b>race</b> across the island.</p>"), (104, b"978-0-545-39187-0")])
    m = read_file_meta(p, fmt)
    assert m.title == "The Mouse Island Marathon"          # the EXTH title beats the short full name
    assert m.authors == ["Geronimo Stilton", "Elisabetta Dami"]
    assert (m.publisher, m.published, m.language) == ("Scholastic Inc.", "2011-11-01", "en")
    assert m.description == "A race across the island."
    assert m.isbn == "9780545391870"
    assert m.title_from_name is False


def test_kindle_full_name_when_theres_no_exth(tmp_path):
    p = kindle_file(tmp_path / "abc.mobi", title="Café Stories", encoding=1252)
    m = read_file_meta(p, "mobi")
    assert m.title == "Café Stories" and m.authors == []


def test_damaged_kindle_files_use_the_filename(tmp_path):
    p = tmp_path / "Wedding Crashers.azw3"
    p.write_bytes(b"BOOKMOBI is not enough")
    assert read_file_meta(p, "azw3").title == "Wedding Crashers"

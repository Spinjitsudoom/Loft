from pathlib import Path

import pytest

from alcove.filemeta import read_file_meta, title_from_filename


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
    from alcove.calibre import html_to_text
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

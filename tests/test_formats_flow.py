import base64
import struct

import pytest

from alcove import fb2, kindle, txt
from alcove.pages import Unreadable
from conftest import png

FB2 = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
 <description><title-info><book-title>Tale</book-title></title-info></description>
 <body>
  <section id="s1"><title><p>Chapter One</p></title>
   <p>It was <emphasis>dark</emphasis> and <strong>stormy</strong>.<a l:href="#n1" type="note">1</a></p>
   <image l:href="#pic"/>
   <section id="s1a"><title><p>A smaller part</p></title><p>Inside.</p></section>
  </section>
  <section><title><p>Chapter Two</p></title><poem><stanza><v>Line one</v><v>Line two</v></stanza></poem></section>
 </body>
 <body name="notes"><section id="n1"><title><p>1</p></title><p>A footnote.</p></section></body>
 <binary id="pic" content-type="image/png">{base64.b64encode(png((5, 6, 7))).decode()}</binary>
</FictionBook>"""


def test_fb2(tmp_path):
    p = tmp_path / "tale.fb2"
    p.write_text(FB2, encoding="utf-8")
    book = fb2.open_fb2(p)
    assert [c.title for c in book.chapters] == ["Chapter One", "Chapter Two", "Notes"]
    assert [(t.title, t.chapter, t.level) for t in book.toc] == [
        ("Chapter One", 0, 0), ("A smaller part", 0, 1), ("Chapter Two", 1, 0), ("Notes", 2, 0)]
    one = book.read(book.chapters[0].href).decode()
    assert "<em>dark</em>" in one and "<strong>stormy</strong>" in one
    assert 'href="chapter-2.xhtml#n1"' in one  # the footnote link points at the notes chapter
    assert 'src="images/pic"' in one
    assert book.resources["images/pic"].media_type == "image/png"
    assert book.read("images/pic") == png((5, 6, 7))
    assert "Line two" in book.read(book.chapters[1].href).decode()


def test_fb2_damaged(tmp_path):
    p = tmp_path / "bad.fb2"
    p.write_text("<FictionBook><body>", encoding="utf-8")
    with pytest.raises(Unreadable) as e:
        fb2.open_fb2(p)
    assert e.value.kind == "damaged"


def test_txt_with_chapters(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("Title page\n\nCHAPTER 1\n\nIt began.\n\nThen more.\n\nChapter 2: The End\n\nIt ended.\n", encoding="utf-8")
    book = txt.open_txt(p)
    assert [c.title for c in book.chapters] == ["Opening", "CHAPTER 1", "Chapter 2: The End"]
    assert "<p>It began.</p>" in book.read(book.chapters[1].href).decode()


def test_txt_without_chapters(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("\n\n".join(f"Paragraph {i} & more" for i in range(100)), encoding="utf-8")
    book = txt.open_txt(p)
    assert [c.title for c in book.chapters] == ["Part 1", "Part 2", "Part 3"]
    assert "&amp; more" in book.read(book.chapters[0].href).decode()


def test_txt_old_encoding(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("Un café, s'il vous plaît.".encode("cp1252"))
    assert "café" in txt.open_txt(p).read("chapter-0.xhtml").decode()


def palm_db(encryption: int) -> bytes:
    header = bytearray(78)
    header[60:68] = b"BOOKMOBI"
    struct.pack_into(">H", header, 76, 1)
    record_list = struct.pack(">II", 86, 0)
    palmdoc = struct.pack(">HHIHHH", 2, 0, 1000, 1, 4096, encryption) + b"\x00\x00"
    return bytes(header) + record_list + palmdoc + b"MOBI" + bytes(200)


def test_kindle_drm_is_protected(cfg, tmp_path):
    p = tmp_path / "locked.azw"
    p.write_bytes(palm_db(encryption=2))
    with pytest.raises(Unreadable) as e:
        kindle.open_kindle(cfg, 1, 1, p)
    assert e.value.kind == "protected"


def test_kindle_garbage_is_damaged(cfg, tmp_path):
    p = tmp_path / "bad.azw3"
    p.write_bytes(b"not a kindle book at all" * 10)
    with pytest.raises(Unreadable) as e:
        kindle.open_kindle(cfg, 2, 1, p)
    assert e.value.kind == "damaged"


def test_old_mobi_links_point_at_the_right_chapter(tmp_path):
    """The MOBI unpacker writes links as #fileposN; after splitting into chapters they must still land."""
    folder = tmp_path / "html"
    folder.mkdir()
    (folder / "book.html").write_text(
        '<html><body><p>Contents: <a href="#filepos900">The end</a></p><mbp:pagebreak/>'
        '<h2>Middle</h2><p>Text.</p><mbp:pagebreak/>'
        '<h2><a id="filepos900"/>The End</h2><p>Done.</p></body></html>', encoding="utf-8")
    book = kindle._html_book(folder)
    assert len(book.chapters) == 3
    first = book.read("chapter-0.xhtml").decode()
    assert 'href="chapter-2.xhtml#filepos900"' in first

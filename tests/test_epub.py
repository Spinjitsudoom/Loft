import zipfile

import pytest

from loft.epub import open_epub
from loft.pages import Unreadable
from conftest import png

CHAPTERS = [("Text/one.xhtml", "<h1>One</h1><p>First.</p>"),
            ("Text/two.xhtml", '<h1 id="t">Two</h1><p id="n2">Second.</p>'),
            ("Text/ch%203.xhtml".replace("%20", " "), "<h1>Three</h1><p>Third.</p>")]


def test_spine_order_and_nav(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS,
                       spine=["Text/two.xhtml", "Text/one.xhtml", "Text/ch 3.xhtml"],
                       nav=[("Two", "Text/two.xhtml", 0), ("Part", "Text/two.xhtml#n2", 1),
                            ("One", "Text/one.xhtml", 0), ("Three", "Text/ch%203.xhtml", 0)])
    book = open_epub(p)
    assert [c.href for c in book.chapters] == ["OEBPS/Text/two.xhtml", "OEBPS/Text/one.xhtml", "OEBPS/Text/ch 3.xhtml"]
    assert [c.title for c in book.chapters] == ["Two", "One", "Three"]
    assert [(t.title, t.chapter, t.anchor, t.level) for t in book.toc] == [
        ("Two", 0, "", 0), ("Part", 0, "n2", 1), ("One", 1, "", 0), ("Three", 2, "", 0)]
    assert b"Second." in book.read(book.chapters[0].href)


def test_ncx_only(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS,
                       ncx=[("One", "Text/one.xhtml", 0), ("Inner", "Text/two.xhtml#n2", 1), ("Three", "Text/ch%203.xhtml", 0)])
    book = open_epub(p)
    assert [(t.title, t.chapter, t.anchor, t.level) for t in book.toc] == [
        ("One", 0, "", 0), ("Inner", 1, "n2", 1), ("Three", 2, "", 0)]


def test_resources_resolve(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS, images={"Images/a b.png": png((1, 2, 3))})
    book = open_epub(p)
    assert book.resources["OEBPS/Images/a b.png"].media_type == "image/png"
    assert book.resolve("OEBPS/Text/one.xhtml", "../Images/a%20b.png") == "OEBPS/Images/a b.png"
    assert book.resolve("OEBPS/Text/one.xhtml", "two.xhtml#n2") == "OEBPS/Text/two.xhtml"
    assert book.chapter_of("OEBPS/Text/two.xhtml") == 1


def test_adobe_drm_is_protected(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS, encryption="http://www.w3.org/2001/04/xmlenc#aes128-cbc")
    with pytest.raises(Unreadable) as e:
        open_epub(p)
    assert e.value.kind == "protected"


def test_font_obfuscation_is_fine(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS, encryption="http://www.idpf.org/2008/embedding")
    assert len(open_epub(p).chapters) == 3


@pytest.mark.parametrize("kind", ["garbage", "no-opf", "empty-spine"])
def test_damaged(tmp_path, kind):
    p = tmp_path / "a.epub"
    if kind == "garbage":
        p.write_bytes(b"not a zip")
    else:
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            if kind == "empty-spine":
                z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                           '<rootfiles><rootfile full-path="c.opf"/></rootfiles></container>')
                z.writestr("c.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata/><manifest/><spine/></package>')
    with pytest.raises(Unreadable) as e:
        open_epub(p)
    assert e.value.kind == "damaged"


def test_sloppy_nav_falls_back_to_ncx(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS, nav=[("One", "Text/one.xhtml", 0)],
                       ncx=[("One", "Text/one.xhtml", 0), ("Three", "Text/ch%203.xhtml", 0)])
    with zipfile.ZipFile(p, "a") as z:  # a hand-made nav with an HTML entity XML can't parse
        z.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>One&nbsp;</nav></body></html>')
    book = open_epub(p)
    assert len(book.chapters) == 3
    assert [t.title for t in book.toc] == ["One", "Three"]


def test_sloppy_nav_without_ncx_means_no_contents(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub", chapters=CHAPTERS, nav=[("One", "Text/one.xhtml", 0)])
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("OEBPS/nav.xhtml", "<html><body><nav>&nbsp;<</nav>")
    book = open_epub(p)
    assert len(book.chapters) == 3 and book.toc == []


def test_oversized_member_is_damaged(tmp_path, make_rich_epub, monkeypatch):
    """A zip bomb: a tiny file whose chapter unpacks to something enormous."""
    from loft import flow
    p = make_rich_epub(tmp_path / "a.epub", chapters=[("Text/one.xhtml", "<p>" + "x" * 5000 + "</p>")])
    monkeypatch.setattr(flow, "MAX_MEMBER", 2000)
    book = open_epub(p)
    with pytest.raises(Unreadable) as e:
        book.read(book.chapters[0].href)
    assert e.value.kind == "damaged"

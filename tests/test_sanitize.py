import pytest

from alcove.epub import open_epub
from alcove.sanitize import chapter_html
from conftest import png

HOSTILE = """<h1 id="top" onclick="steal()">Hello</h1>
<script>alert(1)</script>
<p style="text-align:center; position:fixed; background:url(http://tracker.example/x.png)">Centred</p>
<p style="text-indent: 2em">Indented <a href="javascript:alert(2)">bad link</a> and <a href="http://example.com/x">site</a></p>
<img src="http://tracker.example/pixel.gif" onerror="steal()"/>
<img src="../Images/a%20b.png" alt="pic"/>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><script>alert(3)</script>
  <image xlink:href="../Images/cover.png" width="600" height="800"/></svg>
<form action="http://x"><input name="q"/></form><iframe src="http://x"></iframe><object data="x"></object>
<p>See <a href="two.xhtml#n2">note 2</a> and <a href="#top">the top</a>.</p>
<style>p { color: red }</style>"""


@pytest.fixture
def book(tmp_path, make_rich_epub):
    p = make_rich_epub(tmp_path / "a.epub",
                       chapters=[("Text/one.xhtml", HOSTILE), ("Text/two.xhtml", '<p id="n2">Two</p>')],
                       images={"Images/a b.png": png((1, 2, 3), (60, 90)), "Images/cover.png": png((9, 9, 9), (30, 40))})
    return open_epub(p)


def clean(book):
    raw = book.read(book.chapters[0].href).decode()
    return chapter_html(raw, base=book.chapters[0].href, book=book,
                        image_size=lambda path: {"OEBPS/Images/a b.png": (60, 90), "OEBPS/Images/cover.png": (30, 40)}.get(path),
                        resource_url=lambda path: "/api/files/7/res/" + path.replace(" ", "%20"))


def test_hostile_content_is_removed(book):
    html = clean(book)
    for bad in ("<script", "alert(", "onclick", "onerror", "javascript:", "tracker", "url(", "<form", "<input",
                "<iframe", "<object", "<style", "position", "<svg", "<head", "<body", "steal"):
        assert bad not in html, bad


def test_good_content_survives(book):
    html = clean(book)
    assert '<h1 id="top">Hello</h1>' in html
    assert "text-align:center" in html.replace(" ", "")
    assert "text-indent:2em" in html.replace(" ", "")
    assert 'href="http://example.com/x"' in html and "noopener" in html


def test_images_point_at_the_server(book):
    html = clean(book)
    assert 'src="/api/files/7/res/OEBPS/Images/a%20b.png"' in html
    assert 'width="60"' in html and 'height="90"' in html
    assert 'src="/api/files/7/res/OEBPS/Images/cover.png"' in html  # the SVG cover becomes a plain image


def test_links_between_chapters(book):
    html = clean(book)
    assert 'data-chapter="1"' in html and 'data-anchor="n2"' in html
    assert 'data-chapter="0" data-anchor="top"' in html or ('data-chapter="0"' in html and 'data-anchor="top"' in html)


def test_html_entities_and_bad_markup_dont_break_it(book):
    out = chapter_html("<html><body><p>Caf&eacute; &nbsp;<b>bold<p>unclosed</body></html>", base="OEBPS/Text/x.xhtml",
                       book=book, image_size=lambda p: None, resource_url=lambda p: p)
    assert "Café" in out and "<b>bold</b>" in out.replace("\n", "")


def test_omitted_head_end_tag_keeps_the_text(book):
    out = chapter_html("<html><head><title>T</title><body><p>The whole chapter.</p>", base="OEBPS/Text/x.xhtml",
                       book=book, image_size=lambda p: None, resource_url=lambda p: p)
    assert "The whole chapter." in out

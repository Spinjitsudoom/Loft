"""Fixed-layout books (picture books, many children's books): found, sized, sent whole and safe."""

import zipfile
from pathlib import Path

import pytest

from loft.db import session
from loft.epub import open_epub
from loft.scanner import scan

FIXED = '<meta property="rendition:layout">pre-paginated</meta>'


def fixed_epub(path: Path, *, pages, css=None, fonts=None, images=None, metadata=FIXED, spine_attrs="",
               title="Pictures") -> Path:
    """A small EPUB 3. pages: [(href, body_html, viewport or None)] relative to OEBPS/ (each links every
    stylesheet in css); css: {href: text}; fonts / images: {href: bytes}."""
    css, fonts, images = css or {}, fonts or {}, images or {}
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [f'<item id="p{i}" href="{h}" media-type="application/xhtml+xml"/>' for i, (h, _, _) in enumerate(pages)]
    items += [f'<item id="s{i}" href="{h}" media-type="text/css"/>' for i, h in enumerate(css)]
    items += [f'<item id="f{i}" href="{h}" media-type="{"font/woff2" if h.endswith(".woff2") else "application/vnd.ms-opentype"}"/>'
              for i, h in enumerate(fonts)]
    items += [f'<item id="i{i}" href="{h}" media-type="image/{"png" if h.endswith(".png") else "jpeg"}"/>'
              for i, h in enumerate(images)]
    spine = "".join(f'<itemref idref="p{i}"/>' for i in range(len(pages)))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>A</dc:creator>{metadata}</metadata>
  <manifest>{"".join(items)}</manifest>
  <spine{spine_attrs}>{spine}</spine>
</package>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        z.writestr("OEBPS/content.opf", opf)
        for href, body, viewport in pages:
            depth = href.count("/")
            links = "".join(f'<link href="{"../" * depth}{h}" rel="stylesheet" type="text/css"/>' for h in css)
            vp = f'<meta name="viewport" content="{viewport}"/>' if viewport else ""
            body_tag = body if body.lstrip().startswith("<body") else f"<body>{body}</body>"
            z.writestr(f"OEBPS/{href}", f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xlink="http://www.w3.org/1999/xlink">'
                                         f'<head><title></title>{links}{vp}</head>{body_tag}</html>')
        for href, text in css.items():
            z.writestr(f"OEBPS/{href}", text)
        for href, data in {**fonts, **images}.items():
            z.writestr(f"OEBPS/{href}", data)
    return path


VP = "width=706, height=1024"


# ---------- finding them ----------

def test_a_fixed_layout_book_is_found_with_its_page_sizes(tmp_path):
    book = open_epub(fixed_epub(tmp_path / "b.epub", pages=[("Text/p1.xhtml", "<p>One</p>", VP), ("Text/p2.xhtml", "<p>Two</p>", VP)]))
    assert book.fixed is not None
    assert book.fixed.sizes == [(706, 1024), (706, 1024)]
    assert book.fixed.spread is True and book.fixed.rtl is False


def test_the_kindle_way_of_saying_it_counts_too(tmp_path):
    meta = '<meta name="fixed-layout" content="true"/><meta name="original-resolution" content="600x800"/>'
    book = open_epub(fixed_epub(tmp_path / "b.epub", metadata=meta,
                                pages=[("Text/p1.xhtml", "<p>One</p>", None), ("Text/p2.xhtml", "<p>Two</p>", None)]))
    assert book.fixed.sizes == [(600, 800), (600, 800)]


def test_page_sizes_fall_back_in_order(tmp_path):
    meta = FIXED + '<meta property="rendition:viewport">width=500, height=700</meta>'
    book = open_epub(fixed_epub(tmp_path / "a.epub", metadata=meta,
                                pages=[("Text/p1.xhtml", "<p>One</p>", "width=400, height=600"), ("Text/p2.xhtml", "<p>Two</p>", None)]))
    assert book.fixed.sizes == [(400, 600), (500, 700)]
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1299 1886"><rect width="1" height="1"/></svg>'
    book = open_epub(fixed_epub(tmp_path / "b.epub",
                                pages=[("Text/c.xhtml", svg, None), ("Text/p.xhtml", "<p>Nothing to go on</p>", None),
                                       ("Text/z.xhtml", "<p>Zero</p>", "width=0, height=1024")]))
    assert book.fixed.sizes == [(1299, 1886), (1000, 1500), (1000, 1500)]


def test_spreads_and_direction_come_from_the_book(tmp_path):
    meta = FIXED + '<meta property="rendition:spread">none</meta>'
    book = open_epub(fixed_epub(tmp_path / "b.epub", metadata=meta, spine_attrs=' page-progression-direction="rtl"',
                                pages=[("Text/p1.xhtml", "<p>One</p>", VP)]))
    assert book.fixed.spread is False and book.fixed.rtl is True


def test_flowing_books_are_not_fixed(make_rich_epub, tmp_path):
    book = open_epub(make_rich_epub(tmp_path / "f.epub", chapters=[("Text/one.xhtml", "<p>One</p>")]))
    assert book.fixed is None


def add_to_library(cfg, name: str, **kw) -> int:
    fixed_epub(cfg.books_dirs[0] / "Fixed" / name, **kw)
    scan(cfg)
    with session(cfg.db_path) as con:
        return con.execute("SELECT id FROM book_files WHERE path LIKE ?", (f"%{name}",)).fetchone()["id"]


def test_the_outline_says_so(client, cfg):
    file_id = add_to_library(cfg, "Pictures.epub", pages=[("Text/p1.xhtml", "<p>One</p>", VP), ("Text/p2.xhtml", "<p>Two</p>", VP)])
    outline = client.get(f"/api/files/{file_id}/flow").json()
    assert outline["fixed"] == {"sizes": [[706, 1024], [706, 1024]], "spread": True}
    assert outline["rtl"] is False and len(outline["chapters"]) == 2
    with session(cfg.db_path) as con:
        flowing = con.execute("SELECT id FROM book_files WHERE path LIKE '%Tale.epub'").fetchone()["id"]
    assert "fixed" not in client.get(f"/api/files/{flowing}/flow").json()


# ---------- a page, sent whole and safe ----------

JPEG = b"\xff\xd8\xff\xe0 not really a jpeg"


def page_of(tmp_path, body, *, css=None, fonts=None, images=None, href="Text/p1.xhtml", viewport=VP) -> str:
    from loft.fixedpage import page_document
    book = open_epub(fixed_epub(tmp_path / "b.epub", pages=[(href, body, viewport)], css=css, fonts=fonts,
                                images=images or {"Images/p.jpeg": JPEG}))
    raw = book.read(book.chapters[0].href).decode()
    return page_document(raw, base=book.chapters[0].href, book=book, resource_url=lambda p: f"/api/files/1/res/{p}")


def test_a_page_keeps_its_look(tmp_path):
    from loft.fixedpage import CSP
    css = {"Styles/a.css": "#page0003 .image-container {background: url(../Images/p.jpeg) no-repeat; background-size: 706px 1024px}\n"
                           "@font-face {font-family: T; src: url(../Fonts/t.otf)}\n#div_1 {left: 202px; bottom: 795px; font-family: T}"}
    body = ('<body id="page0003" class="odd book-type-fixed"><div class="image-container"></div>'
            '<div id="text-layer"><div id="div_1" class="textframe">Dear mouse friends,</div></div></body>')
    doc = page_of(tmp_path, body, css=css, fonts={"Fonts/t.otf": b"OTTO"})
    assert doc.lower().startswith("<!doctype html>")
    head = doc.split("<head>", 1)[1]
    assert head.lstrip().startswith(f'<meta http-equiv="Content-Security-Policy" content="{CSP}">')
    assert '<body id="page0003" class="odd book-type-fixed">' in doc
    assert 'id="div_1"' in doc and 'class="textframe"' in doc and "Dear mouse friends," in doc
    assert "url(/api/files/1/res/OEBPS/Images/p.jpeg)" in doc
    assert "url(/api/files/1/res/OEBPS/Fonts/t.otf)" in doc
    assert "left: 202px" in doc or "left:202px" in doc


def test_css_urls_resolve_against_their_stylesheet(tmp_path):
    css = {"Styles/a.css": "@font-face {font-family: T; src: url(../Fonts/t.otf)}"}
    body = ('<body><style>.a {background: url(../Images/p.jpeg)}</style>'
            '<div class="a" style="background-image: url(\'../Images/q.jpeg\')">x</div></body>')
    doc = page_of(tmp_path, body, css=css, fonts={"Fonts/t.otf": b"OTTO"},
                  images={"Images/p.jpeg": JPEG, "Images/q.jpeg": JPEG})
    assert "/api/files/1/res/OEBPS/Fonts/t.otf" in doc
    assert "/api/files/1/res/OEBPS/Images/p.jpeg" in doc
    assert "/api/files/1/res/OEBPS/Images/q.jpeg" in doc


def test_css_never_reaches_outside_the_book(tmp_path):
    css = {
        "Styles/a.css": ".a {background: url(http://x.example/a.png)}\n.b {background: url(//x.example/b.png)}\n"
                        ".c {background: u\\rl(http://x.example/c.png)}\n.d {background: url(\"javascript:alert(1)\")}\n"
                        "@import url(https://x.example/s.css);\n@font-face {font-family: R; src: url(https://x.example/f.woff)}\n"
                        ".e {width: expression(alert(1))}\n.f {behavior: url(x.htc)}\n.g {-moz-binding: url(x.xml)}\n"
                        ".h {background: url(../Images/missing.png)}\n@import \"inside.css\";\n.ok {color: red}",
        "Styles/inside.css": ".from-inside {color: blue}",
    }
    doc = page_of(tmp_path, '<p class="ok">x</p>', css=css).lower()
    for bad in ("http:", "https:", "x.example", "javascript", "expression", "behavior", "binding", "missing", "htc"):
        assert bad not in doc, bad
    assert ".from-inside" in doc and "color: blue" in doc.replace("color:blue", "color: blue")
    assert ".ok" in doc


def test_nothing_that_runs_or_leaves_survives(tmp_path):
    body = ('<body onload="alert(1)"><script>alert(1)</script><img src="../Images/p.jpeg" onerror="alert(2)"/>'
            '<iframe src="https://x.example"></iframe><object data="x.swf"></object><embed src="x.swf"/><embed src="y.swf">'
            '<form action="https://x.example"><input name="q"/></form>'
            '<meta http-equiv="refresh" content="0;url=https://x.example"/><base href="https://x.example/"/>'
            '<link rel="stylesheet" href="https://x.example/s.css"/><a href="javascript:alert(3)">go</a>'
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(4)</script></svg><p>Words</p></body>')
    doc = page_of(tmp_path, body).lower()
    for bad in ("<script", "alert", "onerror", "onload", "<iframe", "<object", "<embed", "<form", "<input",
                "refresh", "<base", "x.example", "javascript"):
        assert bad not in doc, bad
    assert "words" in doc and "/api/files/1/res/oebps/images/p.jpeg" in doc


def test_svg_pictures_are_kept(tmp_path):
    body = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1299 1886" '
            'preserveAspectRatio="xMidYMid meet"><image width="1299" height="1886" xlink:href="../Images/p.jpeg"/></svg>')
    doc = page_of(tmp_path, body)
    assert "<svg" in doc and 'viewbox="0 0 1299 1886"' in doc.lower()
    assert "<image" in doc and "/api/files/1/res/OEBPS/Images/p.jpeg" in doc


def test_the_chapter_route_sends_fixed_pages_whole(client, cfg):
    from loft.fixedpage import CSP
    file_id = add_to_library(cfg, "Whole.epub", pages=[("Text/p1.xhtml", "<p>One</p>", VP)])
    r = client.get(f"/api/files/{file_id}/chapters/0")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP
    assert r.text.lower().startswith("<!doctype html>") and "One" in r.text
    with session(cfg.db_path) as con:
        flowing = con.execute("SELECT id FROM book_files WHERE path LIKE '%Rich.epub'").fetchone()["id"]
    text = client.get(f"/api/files/{flowing}/chapters/0").text
    assert not text.lower().startswith("<!doctype") and "<h1>One</h1>" in text


# ---------- fonts ----------

def test_fonts_in_the_book_are_served(client, cfg):
    file_id = add_to_library(cfg, "Fonts.epub", pages=[("Text/p1.xhtml", "<p>One</p>", VP)],
                             fonts={"Fonts/t.otf": b"OTTO font", "Fonts/w.woff2": b"wOF2 font"})
    r = client.get(f"/api/files/{file_id}/res/OEBPS/Fonts/t.otf")
    assert r.status_code == 200 and r.headers["content-type"] == "font/otf" and r.content == b"OTTO font"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/files/{file_id}/res/OEBPS/Fonts/w.woff2").headers["content-type"] == "font/woff2"


def test_other_files_still_are_not(client, cfg):
    file_id = add_to_library(cfg, "Others.epub", pages=[("Text/p1.xhtml", "<p>One</p>", VP)],
                             css={"Styles/a.css": "p {color: red}"})
    assert client.get(f"/api/files/{file_id}/res/OEBPS/Text/p1.xhtml").status_code == 404
    assert client.get(f"/api/files/{file_id}/res/OEBPS/Styles/a.css").status_code == 404


# ---------- scrambled fonts ----------

def _obfuscated_epub(path: Path, *, algorithm: str, uid: str, font: bytes, stored: bytes) -> Path:
    """A fixed-layout EPUB whose one font is stored scrambled (`stored`), as encryption.xml says."""
    fixed_epub(path, pages=[("Text/p1.xhtml", "<p>One</p>", VP)], fonts={"Fonts/t.otf": stored},
               metadata=FIXED + f'<dc:identifier id="id">{uid}</dc:identifier><dc:identifier>other-id</dc:identifier>')
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("META-INF/encryption.xml", f"""<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData><enc:EncryptionMethod Algorithm="{algorithm}"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/Fonts/t.otf"/></enc:CipherData></enc:EncryptedData></encryption>""")
    return path


FONT = b"OTTO" + bytes(range(256)) * 8


def test_fonts_scrambled_the_adobe_way_are_unscrambled(tmp_path):
    import binascii
    import re as _re
    uid = "urn:uuid:8c64bae9-c40c-44fd-8f31-95c750bfe748"
    key = binascii.unhexlify(_re.sub(r"[^0-9a-f]", "", uid.lower().removeprefix("urn:uuid:"))[:32])
    stored = bytes(b ^ key[i % 16] for i, b in enumerate(FONT[:1024])) + FONT[1024:]
    book = open_epub(_obfuscated_epub(tmp_path / "a.epub", algorithm="http://ns.adobe.com/pdf/enc#RC", uid=uid,
                                      font=FONT, stored=stored))
    assert book.read("OEBPS/Fonts/t.otf") == FONT


def test_fonts_scrambled_the_idpf_way_are_unscrambled(tmp_path):
    import hashlib
    uid = "urn:isbn:9780000000000"
    key = hashlib.sha1(uid.encode()).digest()
    stored = bytes(b ^ key[i % 20] for i, b in enumerate(FONT[:1040])) + FONT[1040:]
    book = open_epub(_obfuscated_epub(tmp_path / "i.epub", algorithm="http://www.idpf.org/2008/embedding", uid=uid,
                                      font=FONT, stored=stored))
    assert book.read("OEBPS/Fonts/t.otf") == FONT


# ---------- found in review ----------

TRICKS = {"Styles/a.css": (
    ".g {width: calc(10px + 2px); color: rgb(1, 2, 3)}\n"     # first: the .c trick below leaves a { open
    ".a {background: ur/**/l(http://evil.example/a.png)}\n"
    ".b {x\;background\\:url\\(\\/\\/evil\\.example\\/b\\.png\\)\;y: red}\n"
    ".c {x\\}@font-face{font-family:Q;src:url(https\\:\\/\\/evil\\.example\\/f\\.woff)}.z{y: red}\n"
    ".d {background: u\\72 l(/api/me)}\n"
    ".e {background: src(\"/api/me\")}\n"
    ".f {background: image-set(\"/api/me\" 1x)}\n")}


def test_the_css_cleaner_cannot_be_tricked(tmp_path):
    body = ('<p class="a" style="x\;background\\:url\\(\\/api\\/me\\)\;y: 1">a</p>'
            '<p style="background: ur/**/l(/api/me)">b</p>')
    doc = page_of(tmp_path, body, css=TRICKS)
    for bad in ("evil", "/api/me", "@font-face{", "src(", "image-set"):
        assert bad not in doc, bad
    assert "calc(10px + 2px)" in doc and "rgb(1, 2, 3)" in doc     # real CSS functions stay


def test_svg_paint_can_only_point_inside_the_page(tmp_path):
    body = ('<svg viewBox="0 0 10 10"><rect width="10" height="10" fill="url(/api/me#a)" clip-path="url(/api/files/1#c)"'
            ' stroke="url(#g)" mask="url(https://evil.example/m)"/><rect width="1" height="1" fill="red"/></svg>')
    doc = page_of(tmp_path, body)
    assert "/api/me" not in doc and "/api/files/1#c" not in doc and "evil" not in doc
    assert 'stroke="url(#g)"' in doc and 'fill="red"' in doc


def test_styles_wrapped_in_cdata_keep_their_rules(tmp_path):
    body = '<body><style><![CDATA[ .k {color: red} ]]></style><style><!-- .m {color: blue} --></style><p class="k">x</p></body>'
    doc = page_of(tmp_path, body)
    assert ".k {color: red}" in doc and ".m {color: blue}" in doc


def test_a_viewport_written_height_first(tmp_path):
    book = open_epub(fixed_epub(tmp_path / "h.epub", pages=[("Text/p1.xhtml", "<p>One</p>", "height=1024, width=706")]))
    assert book.fixed.sizes == [(706, 1024)]
    meta = FIXED + '<meta property="rendition:viewport">height=700, width=500</meta>'
    book = open_epub(fixed_epub(tmp_path / "b.epub", metadata=meta, pages=[("Text/p1.xhtml", "<p>One</p>", None)]))
    assert book.fixed.sizes == [(500, 700)]

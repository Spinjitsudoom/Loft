"""Book HTML made safe to show: a chapter's text and pictures, and nothing that runs or phones home.

Two passes. First Alcove's own rewriter walks the chapter: images get server URLs and their sizes
(so pages can be laid out before they load), links between chapters become data-chapter/anchor
attributes, SVG cover images become plain images. Then nh3 (Ammonia) keeps only an allow-list of
tags, attributes and style properties. The book's stylesheets are never used.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from html.parser import HTMLParser

import nh3

from .flow import FlowBook

TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "span", "br", "hr", "em", "strong", "i", "b", "u", "s",
    "sub", "sup", "small", "blockquote", "pre", "code", "ol", "ul", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "figure", "figcaption", "img", "a",
    "section", "aside", "header", "footer", "nav", "abbr", "cite", "q", "ruby", "rt", "rp", "center",
}
ATTRIBUTES = {
    "*": {"id", "title", "lang", "dir", "style"},
    "img": {"src", "alt", "width", "height"},
    "a": {"href", "data-chapter", "data-anchor"},
    "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"},
    "ol": {"start", "type"},
}
STYLES = {"text-align", "font-style", "font-weight", "font-variant", "text-indent", "margin-left",
          "text-decoration", "vertical-align"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "noscript", "form", "iframe", "object", "embed", "template"}
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "source", "wbr"}
BAD_STYLE = re.compile(r"url\s*\(|expression|@import|javascript:", re.I)


class _Rewriter(HTMLParser):
    def __init__(self, base: str, book: FlowBook, image_size, resource_url) -> None:
        super().__init__(convert_charrefs=True)
        self.base, self.book, self.image_size, self.resource_url = base, book, image_size, resource_url
        self.images = book.images()
        self.out: list[str] = []
        self.skip = 0

    def _emit_tag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool = False) -> None:
        parts = [tag] + [f'{k}="{html.escape(v or "", quote=True)}"' for k, v in attrs]
        self.out.append(f"<{' '.join(parts)}{' /' if close else ''}>")

    def _image(self, src: str | None) -> list[tuple[str, str]] | None:
        path = self.book.resolve(self.base, src or "")
        if not path or path not in self.images:
            return None
        attrs = [("src", self.resource_url(path))]
        size = self.image_size(path)
        if size:
            attrs += [("width", str(size[0])), ("height", str(size[1]))]
        return attrs

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.skip = 0  # a <head> or <title> left open (allowed in HTML) mustn't swallow the chapter
            return
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip:
            return
        a = dict(attrs)
        keep = [(k, v) for k, v in attrs if k in ("id", "title", "lang", "dir", "alt", "colspan", "rowspan", "start", "type")]
        style = "; ".join(d.strip() for d in (a.get("style") or "").split(";")
                          if d.strip() and not BAD_STYLE.search(d))  # drop only the declarations that load things
        if style:
            keep.append(("style", style))
        if tag in ("img", "image"):  # <svg><image xlink:href> is how many EPUB covers are drawn
            src = a.get("src") or a.get("xlink:href") or a.get("href")
            image = self._image(src)
            if image:
                self._emit_tag("img", image + [(k, v) for k, v in keep if k in ("id", "alt")], close=True)
            return
        if tag == "a":
            href = a.get("href") or ""
            if re.match(r"https?://", href, re.I):
                keep.append(("href", href))
            elif href and not re.match(r"[a-z][a-z0-9+.-]*:", href, re.I):
                path = self.book.resolve(self.base, href)
                chapter = self.book.chapter_of(path)
                if chapter is not None:
                    anchor = href.split("#", 1)[1] if "#" in href else ""
                    keep += [("href", "#"), ("data-chapter", str(chapter)), ("data-anchor", anchor)]
        self._emit_tag(tag, keep, close=tag in VOID)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID or tag in ("img", "image"):
            self.handle_starttag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "body":
            return
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID or tag == "image":
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def chapter_html(raw: str, *, base: str, book: FlowBook,
                 image_size: Callable[[str], tuple[int, int] | None],
                 resource_url: Callable[[str], str]) -> str:
    rewriter = _Rewriter(base, book, image_size, resource_url)
    rewriter.feed(raw)
    rewriter.close()
    return nh3.clean(
        "".join(rewriter.out),
        tags=TAGS,
        clean_content_tags=DROP_WITH_CONTENT - {"head"},
        attributes=ATTRIBUTES,
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        filter_style_properties=STYLES,
        strip_comments=True,
    ).strip()

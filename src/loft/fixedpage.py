"""A page of a fixed-layout book, sent whole: the book's own look, and nothing that runs or leaves.

A fixed-layout page (a picture book's) only looks right with its own CSS: pictures are often CSS
backgrounds hung on the page's id, words are placed at exact positions, in the book's fonts. So
unlike flowing chapters (sanitize.py), its CSS is kept, but cleaned with a real CSS parser:
every url() must resolve, against the stylesheet it's written in, to a picture or font inside the
book, and is rewritten to Loft's address for it; anything else, and anything that can run
(expression, behavior, -moz-binding, javascript:), is dropped. @import is followed inside the book
only. The markup keeps its ids, classes and styles (the CSS needs them) and loses scripts, frames,
forms, event handlers and links. The result is one self-contained document with a strict
Content-Security-Policy, which the reader (web/js/fixed.js) shows in a sandboxed, script-less frame.
"""

from __future__ import annotations

import html
import posixpath
import re
from collections.abc import Callable
from html.parser import HTMLParser

import nh3
import tinycss2

from .flow import FlowBook, Resource
from .sanitize import TAGS

CSP = "default-src 'none'; img-src 'self' blob: data:; font-src 'self' blob: data:; style-src 'unsafe-inline'"
FONT_TYPES = {".otf": "font/otf", ".ttf": "font/ttf", ".woff": "font/woff", ".woff2": "font/woff2"}
CSS_TYPES = {"text/css"}
MAX_IMPORTS = 3
SVG_TAGS = {"svg", "g", "image", "rect", "path", "circle", "ellipse", "line", "polygon", "polyline", "defs",
            "use", "text", "tspan", "lineargradient", "radialgradient", "stop", "clippath", "mask", "symbol"}
SVG_ATTRS = {"viewBox", "viewbox", "preserveAspectRatio", "preserveaspectratio", "width", "height", "x", "y",
             "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "transform", "fill", "stroke",
             "stroke-width", "opacity", "fill-opacity", "stroke-opacity", "offset", "stop-color", "href",
             "gradientUnits", "gradientunits", "clip-path", "font-size", "font-family", "text-anchor"}
DROP_WITH_CONTENT = {"script", "noscript", "iframe", "object", "form", "template", "title", "textarea",
                     "select", "button", "head", "applet", "frameset", "audio", "video", "math"}
# Dropped, but what's inside them stays (or, for empty ones like embed, there's nothing inside).
DROPPED = {"meta", "link", "base", "input", "param", "source", "track", "html", "body", "style", "embed", "frame"}
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "source", "wbr", "image", "param",
        "track", "embed", "frame"}
KEEP_ATTRS = {"id", "class", "lang", "dir", "title", "alt", "colspan", "rowspan"}
DANGER = re.compile(r"expression|javascript:|vbscript:|behavior|binding", re.I)
NAME = re.compile(r"-?-?[A-Za-z_][\w-]*\Z")   # a CSS property or function name, written plainly
# The only functions a value may use: none of them loads anything (url() is handled on its own).
FUNCTIONS = {
    "rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color", "color-mix",
    "calc", "min", "max", "clamp", "var", "attr", "counter", "counters", "local", "format", "tech",
    "translate", "translatex", "translatey", "translatez", "translate3d", "rotate", "rotatex", "rotatey",
    "rotatez", "rotate3d", "scale", "scalex", "scaley", "scalez", "scale3d", "skew", "skewx", "skewy",
    "matrix", "matrix3d", "perspective", "linear-gradient", "radial-gradient", "conic-gradient",
    "repeating-linear-gradient", "repeating-radial-gradient", "repeating-conic-gradient", "cubic-bezier",
    "steps", "rect", "inset", "circle", "ellipse", "polygon", "blur", "brightness", "contrast",
    "drop-shadow", "grayscale", "hue-rotate", "invert", "opacity", "saturate", "sepia", "fit-content",
    "minmax", "repeat",
}
AT_RULES = {"font-face", "page", "media", "supports", "keyframes", "-webkit-keyframes"}
SVG_PAINT = {"fill", "stroke", "clip-path", "mask", "filter", "marker-start", "marker-mid", "marker-end"}
LOCAL_REF = re.compile(r"\s*url\(\s*['\"]?#[\w.:-]+['\"]?\s*\)\s*\Z", re.I)
WRAPPERS = re.compile(r"<!\[CDATA\[|\]\]>|<!--|-->")   # around old pages' <style> contents


def fonts(book: FlowBook) -> dict[str, Resource]:
    """The book's fonts, by path, with their media types (from the extension: books label them many ways)."""
    found = {}
    for path, r in book.resources.items():
        kind = FONT_TYPES.get(posixpath.splitext(path)[1].lower())
        if kind:
            found[path] = Resource(path, kind)
    return found


class _Css:
    """The book's CSS, cleaned: see the module's notes."""

    def __init__(self, book: FlowBook, resource_url: Callable[[str], str]) -> None:
        self.book, self.resource_url = book, resource_url
        self.usable = {**book.images(), **fonts(book)}
        self.seen: set[str] = set()
        self.prefix = resource_url("")   # every url() left must start with this: the book's own files

    def safe(self, css: str) -> bool:
        """A last look at cleaned CSS, read afresh: every url() is one of the book's files on Loft,
        and the only at-rules are harmless ones. Anything the cleaning missed fails here."""
        def ok(tokens) -> bool:
            for t in tokens:
                if t.type == "url" and not t.value.startswith(self.prefix):
                    return False
                if t.type == "function":
                    if t.lower_name == "url":
                        arg = "".join(a.value if a.type == "string" else a.serialize() for a in t.arguments).strip()
                        if not arg.startswith(self.prefix):
                            return False
                    if not ok(t.arguments):
                        return False
                if t.type == "at-keyword" and t.lower_value not in AT_RULES:
                    return False
                if t.type in ("() block", "[] block", "{} block") and not ok(t.content):
                    return False
            return True
        return ok(tinycss2.parse_component_value_list(css, skip_comments=True))

    def url(self, raw: str, base: str) -> str | None:
        path = self.book.resolve(base, raw.strip())
        if not path or path not in self.usable:
            return None
        address = self.resource_url(path)
        if re.fullmatch(r"[\w./%:~-]+", address):
            return f"url({address})"
        return 'url("' + address.replace("\\", "\\\\").replace('"', '\\"') + '")'

    def value(self, tokens, base: str) -> str | None:
        """A declaration's value with its urls rewritten, or None when it must go."""
        out = []
        for t in tokens:
            if t.type == "comment":   # a comment still separates: ur/**/l( mustn't become url(
                out.append(" ")
                continue
            if t.type == "url":
                u = self.url(t.value, base)
                if u is None:
                    return None
                out.append(u)
            elif t.type == "function":
                if not NAME.match(t.name):
                    return None
                if t.lower_name == "url":   # url("…"), or an escaped u\rl(…): the argument, however written
                    arg = "".join(a.value if a.type == "string" else a.serialize() for a in t.arguments).strip()
                    u = self.url(arg, base)
                    if u is None:
                        return None
                    out.append(u)
                elif t.lower_name not in FUNCTIONS:
                    return None
                else:
                    inner = self.value(t.arguments, base)
                    if inner is None:
                        return None
                    out.append(f"{t.name}({inner})")
            elif t.type in ("() block", "[] block", "{} block"):
                inner = self.value(t.content, base)
                if inner is None:
                    return None
                out.append({"() block": "(", "[] block": "[", "{} block": "{"}[t.type] + inner
                           + {"() block": ")", "[] block": "]", "{} block": "}"}[t.type])
            else:
                out.append(t.serialize())
        text = "".join(out)
        return None if DANGER.search(text) else text

    def declarations(self, content, base: str) -> str:
        kept = []
        for d in tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True):
            if d.type != "declaration" or not NAME.match(d.name) or DANGER.search(d.lower_name):
                continue
            value = self.value(d.value, base)
            if value is None or not value.strip():
                continue
            decl = f"{d.name}: {value.strip()}{' !important' if d.important else ''}"
            if self.safe(decl):
                kept.append(decl)
        return "; ".join(kept)

    def rules(self, rules, base: str, depth: int) -> list[str]:
        out = []
        for rule in rules:
            if rule.type == "qualified-rule":
                decls = self.declarations(rule.content, base)
                if decls:
                    out.append(f"{tinycss2.serialize(rule.prelude).strip()} {{{decls}}}")
            elif rule.type == "at-rule":
                kw = rule.lower_at_keyword
                if kw == "import":
                    target = next((t.value for t in rule.prelude if t.type in ("url", "string")), None)
                    if target is None:
                        fn = next((t for t in rule.prelude if t.type == "function" and t.lower_name == "url"), None)
                        target = "".join(a.value for a in fn.arguments if a.type == "string") if fn else None
                    path = self.book.resolve(base, target or "")
                    if path:
                        out.append(self.sheet(path, depth + 1))
                elif kw in ("font-face", "page") and rule.content is not None:
                    decls = self.declarations(rule.content, base)
                    if decls:
                        out.append(f"@{kw} {{{decls}}}")
                elif kw in ("media", "supports", "keyframes", "-webkit-keyframes") and rule.content is not None:
                    inner = self.rules(tinycss2.parse_blocks_contents(rule.content, skip_comments=True,
                                                                      skip_whitespace=True), base, depth)
                    prelude = tinycss2.serialize(rule.prelude).strip()
                    if inner and not DANGER.search(prelude) and "url(" not in prelude.lower():
                        out.append(f"@{rule.at_keyword} {prelude} {{{' '.join(inner)}}}")
        return [r for r in out if r and self.safe(r)]

    def sheet(self, path: str, depth: int = 0) -> str:
        """A stylesheet inside the book, cleaned; each once per page, and never outside the book."""
        resource = self.book.resources.get(path)
        if depth > MAX_IMPORTS or path in self.seen or resource is None or resource.media_type not in CSS_TYPES:
            return ""
        self.seen.add(path)
        try:
            text = self.book.read(path).decode("utf-8", "replace")
        except Exception:
            return ""
        return self.text(text, path, depth)

    def text(self, text: str, base: str, depth: int = 0) -> str:
        rules = tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        return "\n".join(self.rules(rules, base, depth))


class _Page(HTMLParser):
    """Walks the page: stylesheets and <style> collected in order, the body's own attributes kept,
    pictures pointed at Loft, links turned to plain text, and the rest left for nh3 to check."""

    def __init__(self, base: str, book: FlowBook, css: _Css, resource_url) -> None:
        super().__init__(convert_charrefs=True)
        self.base, self.book, self.css, self.resource_url = base, book, css, resource_url
        self.images = book.images()
        self.styles: list[str] = []
        self.body_attrs: list[tuple[str, str]] = []
        self.out: list[str] = []
        self.skip = 0
        self.in_style = False
        self.style_text: list[str] = []

    def _attrs(self, tag: str, attrs) -> list[tuple[str, str]]:
        keep = []
        svg = tag in SVG_TAGS
        for k, v in attrs:
            v = v or ""
            if k == "style":
                cleaned = self.css.declarations(v, self.base)
                if cleaned:
                    keep.append(("style", cleaned))
            elif svg and k in SVG_PAINT and "url(" in v.lower() and not LOCAL_REF.match(v):
                continue   # paint and clipping may only point inside the page (url(#id))
            elif k in KEEP_ATTRS or (svg and k in SVG_ATTRS and k != "href") or (tag == "img" and k in ("width", "height")):
                keep.append((k, v))
        return keep

    def _picture(self, attrs) -> str | None:
        a = dict(attrs)
        src = a.get("src") or a.get("xlink:href") or a.get("href")
        path = self.book.resolve(self.base, src or "")
        return self.resource_url(path) if path and path in self.images else None

    def _emit(self, tag: str, attrs: list[tuple[str, str]], close: bool = False) -> None:
        parts = [tag] + [f'{k}="{html.escape(v, quote=True)}"' for k, v in attrs]
        self.out.append(f"<{' '.join(parts)}{' /' if close else ''}>")

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.skip = 0
            self.body_attrs = self._attrs(tag, attrs)
            return
        if tag == "link":
            a = dict(attrs)
            if "stylesheet" in (a.get("rel") or "").lower().split():
                path = self.book.resolve(self.base, a.get("href") or "")
                if path:
                    self.styles.append(self.css.sheet(path))
            return
        if tag == "style":
            self.in_style, self.style_text = True, []
            return
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip or tag in DROPPED:
            return
        keep = self._attrs(tag, attrs)
        if tag in ("img", "image"):
            src = self._picture(attrs)
            if src:
                self._emit(tag, [("src" if tag == "img" else "href", src)] + keep, close=True)
            return
        if tag == "a":
            tag = "span"   # a page is a picture: its links don't go anywhere
        self._emit(tag, keep, close=tag in VOID)

    def handle_startendtag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:   # <iframe/> written as empty: nothing inside to drop
            return
        self.handle_starttag(tag, attrs)
        if tag not in VOID and tag not in ("link", "style", "body"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "style":
            if self.in_style:
                self.styles.append(self.css.text(WRAPPERS.sub(" ", "".join(self.style_text)), self.base))
            self.in_style = False
            return
        if tag in ("body", "link") or tag in DROPPED:
            return
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID:
            return
        self.out.append(f"</{'span' if tag == 'a' else tag}>")

    def handle_data(self, data):
        if self.in_style:
            self.style_text.append(data)
        elif not self.skip:
            self.out.append(html.escape(data, quote=False))


def page_document(raw: str, *, base: str, book: FlowBook, resource_url: Callable[[str], str]) -> str:
    """The whole document for one page of a fixed-layout book (see the module's notes)."""
    css = _Css(book, resource_url)
    page = _Page(base, book, css, resource_url)
    page.feed(raw)
    page.close()
    body = nh3.clean(
        "".join(page.out),
        tags=TAGS | SVG_TAGS | {"span", "div", "img"},
        clean_content_tags={"script", "style"},
        attributes={"*": KEEP_ATTRS | {"style"}, "img": {"src", "width", "height", "alt"},
                    **{t: SVG_ATTRS for t in SVG_TAGS}},
        url_schemes=set(),          # only Loft's own addresses (relative), never another site
        link_rel=None,
        strip_comments=True,
    )
    style = "\n".join(s for s in page.styles if s).replace("</", "<\\/")
    attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in page.body_attrs)
    return (f'<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="{CSP}">'
            f'<meta charset="utf-8"><style>{style}</style></head><body{attrs}>{body}</body></html>')

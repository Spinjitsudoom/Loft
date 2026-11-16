"""FictionBook 2 (.fb2): XML with sections, styled paragraphs, poems, footnotes and embedded images."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from xml.etree import ElementTree as ET

from .flow import FlowBook, TocEntry, Unreadable, memory_book

FB = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK = "{http://www.w3.org/1999/xlink}href"
INLINE = {"emphasis": "em", "strong": "strong", "strikethrough": "s", "sub": "sub", "sup": "sup", "code": "code"}


def _tag(el) -> str:
    return el.tag.split("}", 1)[-1]


def _title(el) -> str:
    t = el.find(f"{{{FB}}}title")
    return " ".join("".join(t.itertext()).split()) if t is not None else ""


class _Converter:
    def __init__(self, where: dict[str, int]) -> None:
        self.where = where  # element id → chapter number

    def inline(self, el) -> str:
        out = [html.escape(el.text or "")]
        for child in el:
            name = _tag(child)
            if name in INLINE:
                out.append(f"<{INLINE[name]}>{self.inline(child)}</{INLINE[name]}>")
            elif name == "a":
                href = child.get(XLINK) or ""
                inner = self.inline(child)
                if href.startswith("#") and href[1:] in self.where:
                    out.append(f'<a href="chapter-{self.where[href[1:]]}.xhtml#{html.escape(href[1:])}">{inner}</a>')
                elif href.startswith(("http://", "https://")):
                    out.append(f'<a href="{html.escape(href)}">{inner}</a>')
                else:
                    out.append(inner)
            elif name == "image":
                out.append(self.image(child))
            else:
                out.append(self.inline(child))
            out.append(html.escape(child.tail or ""))
        return "".join(out)

    def image(self, el) -> str:
        href = (el.get(XLINK) or "").lstrip("#")
        return f'<img src="images/{html.escape(href)}" alt=""/>' if href else ""

    def block(self, el, depth: int) -> str:
        name = _tag(el)
        ident = f' id="{html.escape(el.get("id"))}"' if el.get("id") else ""
        if name == "p":
            return f"<p{ident}>{self.inline(el)}</p>"
        if name == "title":
            level = min(6, depth + 1)
            return f"<h{level}{ident}>" + " ".join(self.inline(p) for p in el) + f"</h{level}>"
        if name == "subtitle":
            return f"<h{min(6, depth + 2)}{ident}>{self.inline(el)}</h{min(6, depth + 2)}>"
        if name == "empty-line":
            return "<br/>"
        if name == "image":
            return f"<p{ident}>{self.image(el)}</p>"
        if name in ("epigraph", "cite"):
            return f"<blockquote{ident}>" + "".join(self.block(c, depth) for c in el) + "</blockquote>"
        if name == "text-author":
            return f"<p{ident}><em>{self.inline(el)}</em></p>"
        if name in ("poem", "stanza"):
            return f"<div{ident}>" + "".join(self.block(c, depth) for c in el) + "</div>"
        if name == "v":
            return f"<p{ident}>{self.inline(el)}</p>"
        if name == "section":
            return f"<section{ident}>" + "".join(self.block(c, depth + 1) for c in el) + "</section>"
        if name == "table":
            rows = "".join("<tr>" + "".join(f"<{_tag(c)}>{self.inline(c)}</{_tag(c)}>" for c in tr) + "</tr>"
                           for tr in el)
            return f"<table{ident}>{rows}</table>"
        return "".join(self.block(c, depth) for c in el)


def open_fb2(path: Path) -> FlowBook:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        raise Unreadable("damaged") from e
    bodies = root.findall(f"{{{FB}}}body")
    main = next((b for b in bodies if b.get("name") not in ("notes", "comments")), None)
    if main is None:
        raise Unreadable("damaged")
    notes = [b for b in bodies if b is not main]

    parts = main.findall(f"{{{FB}}}section") or [main]
    chapters_src: list[tuple[str, list]] = []
    for n, section in enumerate(parts):
        chapters_src.append((_title(section) or f"Part {n + 1}", [section]))
    for body in notes:
        chapters_src.append(("Notes" if body.get("name") == "notes" else "Comments", [body]))

    where: dict[str, int] = {}
    for n, (_, els) in enumerate(chapters_src):
        for el in els:
            for sub in el.iter():
                if sub.get("id"):
                    where.setdefault(sub.get("id"), n)
    conv = _Converter(where)

    toc: list[TocEntry] = []
    built = []
    for n, (title, els) in enumerate(chapters_src):
        body = "".join(conv.block(c, 0) for el in els for c in el)
        built.append((title, body))
        toc.append(TocEntry(title, n, "", 0))
        if n >= len(parts):
            continue  # notes and comments: one entry, not one per footnote
        for el in els:
            for sub in el.iter(f"{{{FB}}}section"):
                if sub is el or sub.get("id") is None:
                    continue
                depth = _depth(el, sub)
                if depth and _title(sub):
                    toc.append(TocEntry(_title(sub), n, sub.get("id"), depth))

    images = {}
    for binary in root.findall(f"{{{FB}}}binary"):
        try:
            images[f"images/{binary.get('id')}"] = (binary.get("content-type", "image/jpeg"),
                                                    base64.b64decode("".join((binary.text or "").split())))
        except (ValueError, TypeError):
            continue
    return memory_book(built, toc, images)


def _depth(root, target) -> int:
    """How many sections deep target sits below root (root's own child sections are depth 1)."""
    def walk(el, d):
        for child in el:
            if child is target:
                return d + 1 if _tag(child) == "section" else d
            found = walk(child, d + 1 if _tag(child) == "section" else d)
            if found is not None:
                return found
        return None
    return walk(root, 0) or 0

"""EPUB 2 and 3: reading order, table of contents and images, straight from the zip."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET

from . import flow
from .flow import Chapter, FlowBook, Resource, TocEntry, Unreadable

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "x": "http://www.w3.org/1999/xhtml",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "enc": "http://www.w3.org/2001/04/xmlenc#",
    "epub": "http://www.idpf.org/2007/ops",
}
# "Encryption" that only scrambles embedded fonts: the text itself is readable.
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _read(z: zipfile.ZipFile, member: str) -> bytes:
    """A file from inside the book, refusing anything that unpacks to more than flow.MAX_MEMBER."""
    if z.getinfo(member).file_size > flow.MAX_MEMBER:
        raise Unreadable("damaged")
    return z.read(member)


def _check_protection(z: zipfile.ZipFile) -> None:
    names = set(z.namelist())
    if "META-INF/sinf.xml" in names:  # Apple FairPlay
        raise Unreadable("protected")
    if "META-INF/encryption.xml" in names:
        root = ET.fromstring(_read(z, "META-INF/encryption.xml"))
        algorithms = {m.get("Algorithm") for m in root.iter(f"{{{NS['enc']}}}EncryptionMethod")}
        if algorithms - FONT_OBFUSCATION:
            raise Unreadable("protected")


def open_epub(path: Path) -> FlowBook:
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise Unreadable("damaged") from e
    try:
        with z:
            _check_protection(z)
            rootfile = ET.fromstring(_read(z, "META-INF/container.xml")).find(".//c:rootfile", NS)
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path:
                raise Unreadable("damaged")
            opf = ET.fromstring(_read(z, opf_path))
            book = _structure(z, opf, opf_path, path)
    except Unreadable:
        raise
    except (KeyError, ET.ParseError, zipfile.BadZipFile, OSError) as e:
        raise Unreadable("damaged") from e
    if not book.chapters:
        raise Unreadable("damaged")
    return book


def _structure(z: zipfile.ZipFile, opf, opf_path: str, path: Path) -> FlowBook:
    base = posixpath.dirname(opf_path)

    def full(href: str) -> str:
        return posixpath.normpath(posixpath.join(base, unquote(href)))

    items = {}
    resources = {}
    nav_path = ncx_path = None
    for item in opf.findall("opf:manifest/opf:item", NS):
        href, media = item.get("href"), item.get("media-type", "")
        if not href:
            continue
        p = full(href)
        items[item.get("id")] = p
        resources[p] = Resource(p, media)
        if "nav" in (item.get("properties") or "").split():
            nav_path = p
        if media == "application/x-dtbncx+xml":
            ncx_path = p
    spine = opf.find("opf:spine", NS)
    if spine is not None and spine.get("toc") in items:
        ncx_path = items[spine.get("toc")]
    chapters = []
    for ref in spine.findall("opf:itemref", NS) if spine is not None else []:
        p = items.get(ref.get("idref"))
        if p and p not in {c.href for c in chapters} and resources[p].media_type in (
                "application/xhtml+xml", "text/html", "application/x-dtbook+xml"):
            chapters.append(Chapter(p))

    def read(member: str) -> bytes:
        try:
            with zipfile.ZipFile(path) as zz:
                return _read(zz, member)
        except (zipfile.BadZipFile, OSError) as e:  # the file changed or the share went away since opening
            raise Unreadable("damaged") from e

    book = FlowBook(chapters=chapters, toc=[], resources=resources, read=read)
    entries = []
    # A contents file that isn't tidy XML (hand-made navs often use &nbsp;) shouldn't cost the whole book:
    # try the EPUB 3 nav, then the older NCX, then go without contents.
    for toc_path, parse in ((nav_path, _nav_entries), (ncx_path, _ncx_entries)):
        if entries or not toc_path or toc_path not in z.namelist():
            continue
        try:
            entries = parse(_read(z, toc_path), toc_path)
        except (ET.ParseError, Unreadable):
            entries = []
    for title, target, level in entries:
        target_path, anchor = urldefrag(target)
        chapter = book.chapter_of(target_path)
        if chapter is not None and title:
            book.toc.append(TocEntry(title, chapter, anchor, level))
    for entry in book.toc:
        if not book.chapters[entry.chapter].title:
            book.chapters[entry.chapter].title = entry.title
    return book


def _resolve_target(doc_path: str, href: str) -> str:
    target, anchor = urldefrag(href or "")
    p = posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), unquote(target)))
    return f"{p}#{anchor}" if anchor else p


def _nav_entries(data: bytes, nav_path: str) -> list[tuple[str, str, int]]:
    root = ET.fromstring(data)
    toc = next((n for n in root.iter(f"{{{NS['x']}}}nav")
                if n.get(f"{{{NS['epub']}}}type") == "toc"), None)
    if toc is None:
        toc = next(root.iter(f"{{{NS['x']}}}nav"), None)
    if toc is None:
        return []
    out: list[tuple[str, str, int]] = []

    def walk(ol, level):
        for li in ol.findall("x:li", NS):
            a = li.find("x:a", NS)
            if a is not None and a.get("href"):
                out.append((_text(a), _resolve_target(nav_path, a.get("href")), level))
            for sub in li.findall("x:ol", NS):
                walk(sub, level + 1)

    for ol in toc.findall("x:ol", NS):
        walk(ol, 0)
    return out


def _ncx_entries(data: bytes, ncx_path: str) -> list[tuple[str, str, int]]:
    root = ET.fromstring(data)
    out: list[tuple[str, str, int]] = []

    def walk(parent, level):
        for point in parent.findall("ncx:navPoint", NS):
            content = point.find("ncx:content", NS)
            if content is not None and content.get("src"):
                out.append((_text(point.find("ncx:navLabel/ncx:text", NS)),
                            _resolve_target(ncx_path, content.get("src")), level))
            walk(point, level + 1)

    nav_map = root.find("ncx:navMap", NS)
    if nav_map is not None:
        walk(nav_map, 0)
    return out

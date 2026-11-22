"""EPUB 2 and 3: reading order, table of contents and images, straight from the zip."""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET

from . import flow
from .flow import Chapter, FixedLayout, FlowBook, Resource, TocEntry, Unreadable

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

    scrambled = _scrambled_fonts(z, opf)

    def read(member: str) -> bytes:
        try:
            with zipfile.ZipFile(path) as zz:
                data = _read(zz, member)
        except (zipfile.BadZipFile, OSError) as e:  # the file changed or the share went away since opening
            raise Unreadable("damaged") from e
        return _unscramble(data, *scrambled[member]) if member in scrambled else data

    book = FlowBook(chapters=chapters, toc=[], resources=resources, read=read,
                    fixed=_fixed_layout(z, opf, spine, chapters))
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


FONT_MAGIC = (b"OTTO", b"\0\1\0\0", b"true", b"ttcf", b"wOFF", b"wOF2")


def _scrambled_fonts(z: zipfile.ZipFile, opf) -> dict[str, tuple[str, list[str]]]:
    """Fonts the book stores scrambled ("font obfuscation", not DRM: it keeps fonts from being lifted
    out of books), by path: the method, and the book's identifiers, its own first, to make the key from."""
    if "META-INF/encryption.xml" not in z.namelist():
        return {}
    try:
        root = ET.fromstring(_read(z, "META-INF/encryption.xml"))
    except (ET.ParseError, Unreadable):
        return {}
    found = {}
    for data in root.iter(f"{{{NS['enc']}}}EncryptedData"):
        method = data.find(f"{{{NS['enc']}}}EncryptionMethod")
        ref = data.find(f".//{{{NS['enc']}}}CipherReference")
        if method is not None and ref is not None and method.get("Algorithm") in FONT_OBFUSCATION and ref.get("URI"):
            found[posixpath.normpath(unquote(ref.get("URI")))] = method.get("Algorithm")
    if not found:
        return {}
    unique = opf.get("unique-identifier")
    ids = [(el.get("id") == unique, (el.text or "").strip()) for el in opf.iter() if str(el.tag).endswith("}identifier")]
    candidates = [text for own, text in sorted(ids, key=lambda i: not i[0]) if text]
    return {path: (method, candidates) for path, method in found.items()}


def _unscramble(data: bytes, method: str, identifiers: list[str]) -> bytes:
    """The font as it was. IDPF: the first 1040 bytes XORed with the SHA-1 of the book's identifier.
    Adobe: the first 1024 bytes XORed with the 16 bytes of its UUID. The key that gives a real font wins."""
    import binascii
    import hashlib

    def xor(key: bytes, length: int) -> bytes:
        head = bytes(b ^ key[i % len(key)] for i, b in enumerate(data[:length]))
        return head + data[length:]

    tried = []
    for ident in identifiers:
        if method == "http://www.idpf.org/2008/embedding":
            tried.append(xor(hashlib.sha1(re.sub(r"[\x20\x09\x0d\x0a]", "", ident).encode()).digest(), 1040))
        else:
            digits = re.sub(r"[^0-9a-fA-F]", "", re.sub(r"^urn:uuid:", "", ident, flags=re.I))
            digits = (digits + digits)[:32]
            if len(digits) >= 2:
                tried.append(xor(binascii.unhexlify(digits[: len(digits) // 2 * 2]), 1024))
    return next((t for t in tried if t[:4] in FONT_MAGIC), tried[0] if tried else data)


FALLBACK_PAGE = (1000, 1500)   # 2:3, when nothing says how big a fixed-layout page is
META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
WIDTH = re.compile(r"width\s*=\s*(\d+(?:\.\d+)?)", re.I)
HEIGHT = re.compile(r"height\s*=\s*(\d+(?:\.\d+)?)", re.I)


def _viewport(text: str) -> tuple[int, int] | None:
    """"width=706, height=1024", in either order."""
    w, h = WIDTH.search(text or ""), HEIGHT.search(text or "")
    return _size(w.group(1), h.group(1)) if w and h else None
VIEWBOX = re.compile(r"""<svg\b[^>]*\bviewBox\s*=\s*["']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)""", re.I)


def _size(w, h) -> tuple[int, int] | None:
    try:
        w, h = round(float(w)), round(float(h))
    except (TypeError, ValueError):
        return None
    return (w, h) if w > 0 and h > 0 else None


def _fixed_layout(z: zipfile.ZipFile, opf, spine, chapters: list[Chapter]) -> FixedLayout | None:
    """Fixed layout when the book says so: rendition:layout pre-paginated, or Kindle's older
    <meta name="fixed-layout" content="true"/>. Each page's size from its viewport, else the book's
    viewport or original resolution, else an SVG page's viewBox, else 2:3."""
    props, names = {}, {}
    metadata = opf.find("opf:metadata", NS)
    for meta in (metadata if metadata is not None else []):
        if not str(meta.tag).endswith("meta"):
            continue
        if meta.get("property"):
            props[meta.get("property")] = (meta.text or "").strip()
        if meta.get("name"):
            names[meta.get("name")] = (meta.get("content") or "").strip()
    if props.get("rendition:layout") != "pre-paginated" and names.get("fixed-layout", "").lower() != "true":
        return None
    book_size = None
    book_size = _viewport(props.get("rendition:viewport", ""))
    if not book_size and (m := re.fullmatch(r"(\d+)\s*x\s*(\d+)", names.get("original-resolution", ""))):
        book_size = _size(*m.groups())
    sizes = []
    for chapter in chapters:
        try:
            text = _read(z, chapter.href).decode("utf-8", "replace")
        except (KeyError, Unreadable, zipfile.BadZipFile, OSError):
            text = ""
        size = None
        for tag in META_TAG.findall(text[:20000]):
            attrs = {k.lower(): v for k, v in ATTR.findall(tag)}
            if attrs.get("name", "").lower() == "viewport":
                size = _viewport(attrs.get("content", ""))
        if not size:
            size = book_size
        if not size and (m := VIEWBOX.search(text)):
            size = _size(*m.groups())
        sizes.append(size or FALLBACK_PAGE)
    return FixedLayout(sizes=sizes, spread=props.get("rendition:spread") != "none",
                       rtl=spine is not None and spine.get("page-progression-direction") == "rtl")


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
